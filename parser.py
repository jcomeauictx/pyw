#!/usr/bin/python -OO
'''
simple pure-python HTML parser

returns something similar to lxml.html etree
'''
import sys, os, logging
try:
    from HTMLParser import HTMLParser as BaseParser
    from htmlentitydefs import name2codepoint
except ImportError:  # python3
    from html.parser import HTMLParser as BaseParser
    from html.entities import name2codepoint
# see https://html.spec.whatwg.org/multipage/syntax.html
CHILDLESS = (  # elements that cannot contain subelements
    'area',
    'base',
    'br',
    'col',
    'command',
    'embed',
    'hr',
    'img',
    'input',
    'keygen',
    'link',
    'meta',
    'param',
    'source',
    'track',
    'wbr',
)
AUTOCLOSE = {  # elements which automatically close if followed by certain tags
    'p': ('address', 'article', 'aside', 'blockquote', 'details', 'div', 'dl',
          'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2',
          'h3', 'h4', 'h5', 'h6', 'header', 'hgroup', 'hr', 'main', 'menu',
          'nav', 'ol', 'p', 'pre', 'section', 'table', 'ul'),
    'rt': ('rt', 'rp'),
}
class ParserError(ValueError):
    pass

class Element(object):
    '''
    representation of an HTML element
    '''
    def __init__(self, tag, attributes, **kwargs):
        self.tag = tag
        self.attrib = dict(attributes)
        self.text = None
        self.tail = None
        self.children = []
        for arg in kwargs:
            setattr(self, arg, kwargs[arg])

    def iterchildren(self):
        return iter(self.children)

    def __repr__(self):
        return '<Element <%s %s> text=%r tail=%r children=%s>' % (
                self.tag, self.attrib, clean(self.text), clean(self.tail),
                len(self.children))
    __str__ = __repr__
    
    def getroot(self):
        '''
        brain-dead implementation assumes this element *is* the root
        '''
        return self

    def xpath(self, path):
        '''
        only intended for //body and only descends to where it finds one or more
        '''
        if not path.startswith('//'):
            raise NotImplementedError('Only accepts xpath format //tag')
        else:
            root = self
            tag = path[2:]
            for child in root.children:
                if child.tag == tag:
                    return [element for element in root.children
                            if element.tag == tag]
                else:
                    result = child.xpath(path)
                    if result:
                        return result
            if tag == 'body':  # it must not have been found
                # assuming this is the 'etree' element, make *this* the body
                logging.debug('xpath has not found %r from %r', tag, self.tag)
                if self.tag == 'etree':
                    self.tag == tag 
                    return [self]
            logging.error('xpath cannot find %r', tag) 

class HTMLParser(BaseParser):
    '''
    minimal HTML parser

    *must* pass in base_url!
    '''
    def __init__(self, *args, **kwargs):
        # can't use super because python2 implementation is old-style class
        BaseParser.__init__(self, *args)  # don't pass in kwargs
        for arg in kwargs:
            logging.debug('Parser setting %s to %s', arg, kwargs[arg])
            setattr(self, arg, kwargs[arg])
        self.stack = [Element('etree', [], docinfo=type('Docinfo', (),
                                                        {'encoding': 'utf8'}),
                                           base_url=self.base_url)]

    def handle_starttag(self, tag, attributes):
        logging.debug('starttag: %s, attributes: %s', tag, attributes)
        parent = self.stack[-1].tag
        if parent in CHILDLESS:
            logging.warning('closing previous %r tag', parent)
            self.handle_endtag(parent)
        elif parent in tuple(AUTOCLOSE.keys()) and tag in AUTOCLOSE[parent]:
            logging.warning('autoclosing previous %r tag', parent)
            self.handle_endtag(parent)
        self.stack.append(Element(tag, attributes, base_url=self.base_url))

    def handle_endtag(self, tag):
        expected = self.stack[-1].tag
        logging.debug('endtag: %s, expected: %s', tag, expected)
        if expected != tag:
            logging.error('Unexpected end tag %r instead of %r',
                          tag, expected)
            while self.stack[-1].tag != tag and len(self.stack) > 3:
                logging.warning('Forcing %s closed', self.stack[-1])
                self.handle_endtag(self.stack[-1].tag)
        try:
            self.stack[-2].children.append(self.stack.pop(-1))
        except IndexError:
            logging.error('No place for child node to go')

    def handle_data(self, data):
        logging.debug('data: %s', data)
        if self.stack[-1].text is None:
            self.stack[-1].text = data
        else:
            try:
                self.stack[-1].children[-1].tail = data
            except IndexError:
                logging.error('No place for tail data %r in etree', data)

def clean(string):
    '''
    clean text or None to show in Element.__repr__
    '''
    if string is None:
        return None
    else:
        return string.strip()

def parse(file_object, parser=None):
    '''
    parse data and return etree
    '''
    logging.debug('file_object: %s', file_object)
    try:
        base_url = (getattr(file_object, 'url', None) or
                    getattr(file_object, 'name'))
    except AttributeError:
        logging.debug('file has no name attribute: %s', dir(file_object))
        if hasattr(file_object, 'url'):
            logging.debug('file_object.url: %s', file_object.url)
        raise
    parser = HTMLParser(base_url=base_url)
    parser.feed(decode(file_object.read()))
    parser.close()
    if len(parser.stack) != 1:
        raise ParserError('Parsed incorrectly into %s' % parser.stack)
    else:
        etree = parser.stack[0]
        logging.debug('etree.docinfo.encoding: %s', etree.docinfo.encoding)
        return etree

def encode(text, encoding='utf8'):
    '''
    curses stdscr.addstr(text) requires unicode encoded to utf8

    but we could be getting already-encoded bytes, depending on whether
    we're using Python version 2 or 3
    '''
    try:
        return text.encode(encoding)
    except UnicodeDecodeError:
        return text

def decode(text, encoding='utf8'):
    '''
    HTMLParser under Python3 requires Unicode not bytes
    '''
    try:
        return text.decode(encoding)
    except UnicodeDecodeError:
        return text

if __name__ == '__main__':
    # test program
    logging.basicConfig(level=logging.DEBUG if __debug__ else logging.INFO)
    sys.argv.append('test.html')
    with open(sys.argv[1], 'r') as infile:
        logging.debug('origin: %s', infile.name)
        logging.debug('body: %s', parse(infile).xpath('//body'))
