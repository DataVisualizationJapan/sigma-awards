"""Small, offline HTML tree reader for the saved DJA pages (stdlib only)."""
import re
from html.parser import HTMLParser


def clean(value):
    return re.sub(r'\s+', ' ', value).strip()


class Node:
    def __init__(self, tag='', attrs=(), parent=None, pos=0):
        self.tag, self.attrs, self.parent, self.pos = tag, dict(attrs), parent, pos
        self.children = []

    @property
    def text(self):
        return clean(self.raw_text())

    def raw_text(self):
        if self.tag in ('script', 'style', 'noscript'):
            return ''
        return ''.join(c.raw_text() if isinstance(c, Node) else c for c in self.children)

    def has_class(self, name):
        return name in self.attrs.get('class', '').split()

    def nodes(self, tag=None, cls=None):
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (cls is None or child.has_class(cls)):
                    yield child
                yield from child.nodes(tag, cls)

    def first(self, tag=None, cls=None):
        return next(self.nodes(tag, cls), None)


class Tree(HTMLParser):
    VOID = set('area base br col embed hr img input link meta param source track wbr'.split())

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.counter = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        # Old WordPress HTML contains unclosed paragraphs and optional li/td tags.
        if tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'table', 'ul', 'blockquote'):
            for i in range(len(self.stack)-1, 0, -1):
                if self.stack[i].tag == 'p':
                    self.stack = self.stack[:i]
                    break
                if self.stack[i].tag in ('div', 'td', 'li', 'body'):
                    break
        if tag in ('li', 'td', 'tr'):
            for i in range(len(self.stack)-1, 0, -1):
                if self.stack[i].tag == tag:
                    self.stack = self.stack[:i]
                    break
                if self.stack[i].tag in ('table', 'ul', 'ol'):
                    break
        self.counter += 1
        node = Node(tag, attrs, self.stack[-1], self.counter)
        self.stack[-1].children.append(node)
        if tag == 'br':
            node.children.append('\n')
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)
