#!/usr/bin/python -OO
'''
minimalist text web browser
'''
#pylint: disable=multiple-imports, eval-used
from __future__ import print_function
import sys, os, tempfile, logging, curses, locale
from collections import defaultdict, OrderedDict
from parser import encode, decode
# if you want more robust HTTP and HTML handling, and don't mind it not being
# pure Python, use `from lxml import html`.
if os.getenv('IMPURE_PYTHON'):
    from lxml import html
else:
    import parser as html
try:
    import urllib2, urlparse, cookielib
except ImportError:
    import urllib.parse as urlparse
    import urllib.request as urllib2
    import http.cookiejar as cookielib
# log to a file, because curses takes over stdin and stderr
LOGDIR = tempfile.gettempdir()
LOGFILE = os.path.join(LOGDIR, 'pyw.log')
logging.basicConfig(filename=LOGFILE,
                    level=logging.DEBUG if __debug__ else logging.INFO)
# fix unicode display on python2
# https://stackoverflow.com/a/40082903/493161
locale.setlocale(locale.LC_ALL, '')
if sys.stdin.isatty():
    WINDOW = curses.initscr()
    WINDOW.keypad(True)
    HEIGHT, WIDTH = WINDOW.getmaxyx()
else:
    WINDOW = None
    HEIGHT, WIDTH = None, None
DEFAULT_URL = os.getenv('PYW_STARTPAGE', 'https://startpage.com/')
USER_AGENT = os.getenv('PYW_USER_AGENT', 'Mozilla/5.0 '
                       '(X11; U; Linux i686; en-US; rv:1.9.0.16)')
MAXLINES = 10000
ACTIONS = {
    'j': 'advance_page',
    ' ': 'advance_page',
    'p': 'back_one_page',
    '\t': 'advance_cursor',
    '\n': 'activate',
}
# display attributes for tags
# tag: [attribute, newline_before, newline_after]
DEFAULT = [curses.A_NORMAL, False, False]
DISPLAY = defaultdict(lambda: DEFAULT, {
    'a': [curses.A_UNDERLINE, False, False],
    'h1': [curses.A_BOLD, True, True],
    'h2': [curses.A_BOLD, True, True],
    'h3': [curses.A_BOLD, True, True],
    'h4': [curses.A_BOLD, True, True],
    'h5': [curses.A_BOLD, True, True],
    'h6': [curses.A_BOLD, True, True],
    'p': [curses.A_NORMAL, True, True],
    'div': [curses.A_NORMAL, True, True],
})

def init():
    '''
    set up opener and other necessary stuff
    '''
    userdir = os.path.join(os.path.expanduser('~'), '.pyw')
    if not os.path.exists(userdir):
        logging.debug('creating storage directory %s', userdir)
        os.mkdir(userdir)
    else:
        logging.debug('using existing directory %s', userdir)
    cookiefile = os.path.join(userdir, 'cookies.txt')
    cookiejar = cookielib.MozillaCookieJar()
    if os.path.exists(cookiefile):
        cookiejar.load(cookiefile)
    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookiejar))
    opener.addheaders = [['User-agent', USER_AGENT]]
    urllib2.install_opener(opener)

def fetch(terms=None):
    '''
    get webpage
    '''
    terms = terms or [DEFAULT_URL]
    logging.debug('terms: %s', terms)
    if len(terms) == 1:
        page = urllib2.urlopen(canonicalize(terms[0]))
        logging.info('page.info: %s', page.info())
    else:
        raise NotImplementedError('Search engine support not yet implemented')
    tree = html.parse(page)
    page.close()
    return tree

def pyw(window=WINDOW, args=None):
    '''
    navigate the web, starting at website
    '''
    logging.debug('arguments: %s, %s', window, args)
    tree = fetch(args)
    body = tree.getroot().xpath('//body')[0]
    encoding = tree.docinfo.encoding or 'utf8'
    logging.debug('base URL: %s, encoding: %s', body.base_url, encoding)
    if window is None:  # just dump to stdout
        page = body.text_content()
        ignored, text, ignored = cleanup(page) #pylint: disable=unused-variable
        print(text)
    else:
        window.clear()
        window.refresh()  # https://stackoverflow.com/a/22121866/493161
        windowbuffer = curses.newpad(MAXLINES, WIDTH)
        in_key = ''
        line = 0
        links = OrderedDict({(0, 0): '.'})
        while in_key != 'q':
            windowbuffer.clear()
            render(windowbuffer, body, links)
            if links:
                curses.curs_set(1)  # make cursor visible
                logging.debug('links: %s', links)
            logging.debug('displaying from line %d', line)
            windowbuffer.refresh(line, 0, 0, 0, HEIGHT - 1, WIDTH - 1)
            in_key = window.getkey()
            line = do_associated_action(in_key, line, links, body.base_url)

def render(screen, element, links, parent_attributes=curses.A_NORMAL,
           need_space=False):
    '''
    add rendered element to screen

    recursive function. also, builds links dict.
    '''
    if element.tag in ('script', 'style'):
        return need_space
    attributes, newline_before, newline_after = DISPLAY[element.tag]
    attributes = (attributes | parent_attributes, parent_attributes)
    if newline_before:
        screen.addstr('\n')
    space, text, need_space = cleanup(element.text, need_space)
    if text:
        screen.addstr(space, attributes[1])
        if element.attrib.get('href'):
            links[screen.getyx()] = element.attrib['href']
        logging.debug('element.text: %r, %r', text, encode(text))
        screen.addstr(encode(text), attributes[0])
    space, text, need_space = cleanup(element.tail, need_space)
    if text:
        screen.addstr(space, attributes[1])
        logging.debug('element.tail: %r, %r', text, encode(text))
        screen.addstr(encode(text), attributes[1])
    for child in element.iterchildren():
        need_space = render(screen, child, links, attributes[0], need_space)
    if newline_after:
        screen.addstr('\n')
        need_space = False
    return need_space

def do_associated_action(keyhit, line, links, base_url):
    '''
    map keyhit to action, and execute it
    '''
    logging.debug('keyhit: %s', keyhit)
    if keyhit in ACTIONS:
        line = eval(ACTIONS[keyhit])(line, links, base_url)
    elif keyhit != 'q':
        logging.warning('no association for "%s"', keyhit)
    return line

def advance_page(line, links, base_url):  #pylint: disable=unused-argument
    '''
    go forward one page in buffer
    '''
    index = line + HEIGHT
    if index > MAXLINES - HEIGHT:
        index = MAXLINES - HEIGHT
    return index

def back_one_page(line, links, base_url):  #pylint: disable=unused-argument
    '''
    go back one page in buffer
    '''
    index = line - HEIGHT
    if index < 0:
        index = 0
    return index

def advance_cursor(line, links, base_url):  #pylint: disable=unused-argument
    '''
    move cursor to next link or form field
    '''
    locations = list(links.keys())
    here = WINDOW.getyx()
    new = locations.index(here) + 1
    WINDOW.move(*locations[new])
    return line

def activate(line, links, base_url):  # pylint: disable=unused-argument
    '''
    visit link at cursor, or submit current form
    '''
    here = WINDOW.getyx()
    href = urlparse.urljoin(base_url, links[here])
    logging.debug('going to: %s', href)
    pyw(WINDOW, [href])
    return 0  # back to line 1

def cleanup(string, need_space=False):
    '''
    get rid of extra spaces and CRLFs
    '''
    not_none = string or ''  # make sure string is not None
    clean = ' '.join(not_none.split())
    all_spaces = not_none.isspace()
    space_preceding = ''
    if clean and not all_spaces:
        if need_space:
            space_preceding = ' '
        if not_none[-1].isspace():
            need_space = True
    elif all_spaces:
        need_space = True
    return space_preceding, clean, need_space

def canonicalize(url):
    '''
    make sure we have a complete URL
    '''
    parsed = urlparse.urlparse(url)
    if not parsed.scheme and not parsed.netloc:
        parsed = parsed._replace(scheme='http', netloc=parsed.path, path='/')
    return urlparse.urlunparse(parsed)

if __name__ == '__main__':
    # action on invoking program directly rather than importing it
    init()
    if WINDOW:
        try:
            curses.wrapper(pyw, sys.argv[1:])  # WINDOW is automatically passed
        except Exception:
            logging.exception("Program error")
            raise
    else:
        pyw(WINDOW, sys.argv[1:])
