#!/usr/bin/env python2
# term.py
# terminal buffer emulator

import sys
import re

def intgroups(m):
    return [int(d) for d in m.groups() if d and d.isdigit()]


class Terminal(object):
    ESCAPE = '\033'

    def __init__(self, cols, rows, debug=False):
        self.debug = debug
        self.cols = cols
        self.rows = rows
        self.scroll = (1, rows)
        self.row = 1
        self.col = 1
        # chars are stored at self.buf[row][col]
        self.pending = ''
        self.reset()

    def reset(self):
        self.buf = [[' '] * self.cols for i in range(self.rows)]

    def move(self, row=None, col=None, rel=False):
        if rel:
            row = self.row + row or 1
            col = self.col + col or 1
        else:
            if row is None:
                row = self.row
            if col is None:
                col = self.col

        if col > self.cols:
            row += 1
            col = 1
        if col < 1:
            col = self.cols
            row -= 1

        start, end = self.scroll
        if row < start:
            row = start
        if row > end:
            self.del_lines(1, start-1)
            row = end

        self.row = row
        self.col = col

    def rel(self, row=None, col=None):
        self.move(row, col, rel=True)

    def erase(self, start, end):
        save = self.row, self.col
        for row in range(start[0], end[0]):
            for col in range(start[1], end[1]):
                self.move(row, col)
                self.puts(' ')
        self.row, self.col = save

    def del_lines(self, num=1, row=None):
        if row is None:
            row = self.row

        for i in range(num):
            del self.buf[row - 1]
            self.buf.insert(self.scroll[1] - 1, [' '] * self.cols)

    def puts(self, s, move=True):
        if isinstance(s, int):
            s = chr(s)
        for c in s:
            self.buf[self.row-1][self.col-1] = c
            if move:
                self.move(self.row, self.col + 1)

    def sequence(self, data, i):
        if self.debug:
            print('control character!', repr(data[i:i+8]))
        return 1

    def pre(self, data, i):
        b = data[i]
        if b == self.ESCAPE:
            return self.sequence(data, i)
        elif b == '\b':
            self.col = max(0, self.col - 1)
            self.puts(' ', move=False)
            return 1
        elif b == '\r':
            self.move(col=1)
            return 1
        elif b == '\n':
            self.move(self.row + 1, 1)
            return 1
        elif b == '\x07':
            # beep
            return 1
        else:
            if self.debug:
                sys.stdout.write(b)
            return None

    def append(self, data):
        if isinstance(data, bytes):
            data = data.decode('utf8', 'replace')
        data = self.pending + data
        self.pending = ''
        i = 0
        while i < len(data):
            pre = self.pre(data, i)
            if pre == 0:
                if i > len(data) - 8:
                    # we might need more data to complete the sequence
                    self.pending = data[i:]
                    return
                else:
                    # looks like we don't know how to read this sequence
                    if self.debug:
                        print('unknown!', repr(data[i:i+8]))
                    i += 1
                    continue
            elif pre is not None:
                i += pre
                continue
            else:
                self.puts(data[i])
                i += 1

    def dump(self):
        return ''.join(col for row in self.buf for col in row + ['\n'])

    def __str__(self):
        return '<{} ({},{})+{}x{}>'.format(
            self.__class__,
            self.row, self.col, self.cols, self.rows)


class VT100(Terminal):
    control = None
    KEYMAP = {
        'backspace': '\b',
        'enter': '\n',
        'escape': '\033',
        'space': ' ',
        'up': '\033[A',
        'down': '\033[B',
        'right': '\033[C',
        'left': '\033[D',
    }

    @classmethod
    def map(cls, key):
        return cls.KEYMAP.get(key, key)

    def __init__(self, *args, **kwargs):
        if not self.control:
            self.control = []

        # control character handlers
        REGEX = (
            # cursor motion
            (r'\[(\d+)A', lambda g: self.rel(-g[0], 0)),
            (r'\[(\d+)B', lambda g: self.rel(g[0], 0)),
            (r'\[(\d+)C', lambda g: self.rel(0, g[0])),
            (r'\[(\d+)D', lambda g: self.rel(0, -g[0])),
            (r'\[(\d+);(\d+)[Hf]', lambda g: self.move(g[0], g[1])),
            # set scrolling region
            (r'\[(\d+);(\d+)r', lambda g: self.set_scroll(g[0], g[1])),
            # remove lines from cursor
            (r'\[(\d+)M', lambda g: self.del_lines(g[0])),
            # erase from cursor to end of screen
            (r'\[0\?J', lambda g: self.erase(
                (self.row, self.col), (self.rows, self.cols))),
            # noop
            (r'\[\?(\d+)h', None),
            (r'\[([\d;]+)?m', None),
        )
        SIMPLE = (
            ('[A', lambda: self.rel(row=-1)),
            ('[B', lambda: self.rel(row=1)),
            ('[C', lambda: self.rel(col=1)),
            ('[D', lambda: self.rel(col=1)),
            ('[H', lambda: self.move(1, 1)),
            ('[2J', lambda: self.reset()),
            ('[K', lambda: self.erase(
                (self.row, self.col), (self.row + 1, self.cols))),
            ('[M', lambda: self.del_lines(1, row=self.row + 1)),
            # noop
            ('>', None),
            ('<', None),
            ('[?1l', None),
            ('=', None),
        )

        for r, func in REGEX:
            r = re.compile(r)
            self.control.append((r, func))

        for s, func in SIMPLE:
            r = re.compile(re.escape(s))
            if func:
                def wrap(func):
                    return lambda g: func()

                func = wrap(func)
            self.control.append((r, func))

        super(self.__class__, self).__init__(*args, **kwargs)

    def sequence(self, data, i):
        def call(func, s, groups):
            if func:
                if self.debug:
                    print()
                    print('<ESC "{}">'.format(s))
                func(groups)
            else:
                if self.debug:
                    print()
                    print('<NOOP "{}">'.format(s))
            return len(s)

        context = data[i+1:i+10]
        if not context:
            return 0
        for r, func in self.control:
            m = r.match(context)
            if m:
                return 1 + call(func, m.group(), intgroups(m))

        return 0

    def set_scroll(self, start, end):
        self.scroll = (start, end)

if __name__ == '__main__':
    def debug():
        v = VT100(142, 32, debug=True)
        data = sys.stdin.read()
        print('-= begin input =-')
        print(repr(data))
        print('-= begin parsing =-')
        for b in data:
            v.append(b)
        print('-= begin dump =-')
        print(repr(v.dump()))
        print('-= begin output =-')
        sys.stdout.write(v.dump())

    def static():
        v = VT100(142, 32)
        data = sys.stdin.read()
        v.append(data)
        sys.stdout.write(v.dump())

    def stream():
        v = VT100(80, 24)
        while True:
            b = sys.stdin.read(1)
            if not b:
                break
            v.append(b)
            print('\r\n'.join(v.dump().rsplit('\n')[-3:-1]) + '\r')
            print(v.row, v.col, '\r')
            # sys.stdout.write(v.dump() + '\r')
            # sys.stdout.flush()

    stream()
