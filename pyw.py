#!/usr/bin/python -OO
'''
minimalist text web browser
'''
#pylint: disable=multiple-imports, eval-used
from __future__ import print_function
import sys, os, tempfile, logging, curses, locale
from collections import defaultdict, OrderedDict
from parser import encode
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
    HEIGHT -= 1  # make room for a status line
else:
    WINDOW = None
    HEIGHT, WIDTH = None, None
DEFAULT_URL = os.getenv('PYW_STARTPAGE', 'https://startpage.com/')
USER_AGENT = os.getenv('PYW_USER_AGENT', 'Mozilla/5.0 '
                       '(X11; U; Linux i686; en-US; rv:1.9.0.16)')
MAXLINES = 10000
# a lot of these actions borrowed from lynx, links, and w3m
ACTIONS = {
    'j': 'screen_down',
    ' ': 'screen_down',
    'p': 'screen_up',
    '\t': 'advance_cursor',
    'KEY_BTAB': 'backup_cursor',
    '\n': 'activate',
    'KEY_LEFT': 'previous_page',
    'B': 'previous_page',
}
PAGES = []  # list of Pages being traversed
STATE = {  # global state
    'urlindex': -1,  # -1 forces load of most recently appended URL
}
# display attributes (style) for tags
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

class Page(object):  #pylint: disable=useless-object-inheritance
    '''
    encapsulates a URL with its content, linklist, and display state
    '''

    def __init__(self, url):
        '''
        initialize a new Page object
        '''
        self.url = canonicalize(url)
        self.links = OrderedDict({(0, 0): '.'})
        self.buffer = curses.newpad(MAXLINES, WIDTH)
        self.needs_redraw = True
        self.line = 0  # index into buffer of first line showing
        self.curpos = (-1, -1)  # cursor position
        self.etree = None
        self.fetch()

    def fetch(self):
        '''
        fetch the contents of the URL and set attributes accordingly
        '''
        page = urllib2.urlopen(self.url)
        self.etree = html.parse(page)
        page.close()

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

def pyw(window=WINDOW, url=None):
    '''
    navigate the web, starting at website
    '''
    in_key = ''
    while in_key != 'q':
        if url and not PAGES:
            PAGES.append(Page(url))
        if STATE['urlindex'] == -1:
            STATE['urlindex'] = len(PAGES) - 1
        page = PAGES[STATE['urlindex']]
        body = page.etree.getroot().xpath('//body')[0]
        encoding = page.etree.docinfo.encoding or 'utf8'
        logging.debug('base URL: %s, encoding: %s', body.base_url, encoding)
        if window is None:  # just dump to stdout
            #pylint: disable=unused-variable
            ignored, text, ignored = cleanup(body.text_content())
            print(text)
            in_key = 'q'
            break
        elif page.needs_redraw:
            logging.debug('redrawing page from line %d', page.line)
            window.clear()
            window.refresh()  # https://stackoverflow.com/a/22121866/493161
            render(page.buffer, body)
            page.needs_redraw = False
        if page.curpos != (-1, -1):
            cursor_position = list(page.curpos)
            cursor_position[0] %= HEIGHT
            logging.debug('setting cursor to %s', tuple(cursor_position))
            window.move(*cursor_position)
            curses.curs_set(2)  # make cursor visible
        logging.debug('links: %s', page.links)
        logging.debug('displaying from line %d', page.line)
        page.buffer.refresh(page.line, 0, 0, 0, HEIGHT - 1, WIDTH - 1)
        in_key = window.getkey()
        do_associated_action(in_key)

def render(screen, element, parent_style=curses.A_NORMAL, need_space=False):
    '''
    add rendered element to screen

    recursive function. also, builds links dict.
    '''
    if element.tag in ('script', 'style'):
        return need_space
    links = PAGES[STATE['urlindex']].links
    style, newline_before, newline_after = DISPLAY[element.tag]
    style = (style | parent_style, parent_style)
    if newline_before:
        screen.addstr('\n')
    space, text, need_space = cleanup(element.text, need_space)
    if text:
        screen.addstr(space, style[1])
        if element.attrib.get('href'):
            links[screen.getyx()] = element.attrib['href']
        logging.debug('element.text: %r, %r', text, encode(text))
        screen.addstr(encode(text), style[0])
    space, text, need_space = cleanup(element.tail, need_space)
    if text:
        screen.addstr(space, style[1])
        logging.debug('element.tail: %r, %r', text, encode(text))
        screen.addstr(encode(text), style[1])
    for child in element.iterchildren():
        need_space = render(screen, child, style[0], need_space)
    if newline_after:
        screen.addstr('\n')
        need_space = False
    return need_space

def do_associated_action(keyhit):
    '''
    map keyhit to action, and execute it
    '''
    logging.debug('keyhit: %s', keyhit)
    if keyhit in ACTIONS:
        eval(ACTIONS[keyhit])(PAGES[STATE['urlindex']])
    elif keyhit != 'q':
        logging.warning('no association for "%s"', keyhit)

# actions resulting from keyhits
def screen_down(webpage):
    '''
    go forward one page in buffer
    '''
    index = webpage.line + HEIGHT
    if index > webpage.buffer.getyx()[0]:
        logging.debug('already at end of page')
        return
    webpage.line = index

def screen_up(webpage):
    '''
    go back one page in buffer
    '''
    index = webpage.line - HEIGHT
    if index < 0:
        logging.debug('already at beginning of page')
        return
    webpage.line = index

def advance_cursor(webpage):
    '''
    move cursor to next link or form field
    '''
    locations = list(webpage.links.keys())
    here = add_height(webpage.line, WINDOW.getyx())
    logging.debug('here: %s, adjusted: %s', WINDOW.getyx(), here)
    new = subtract_height(webpage.line, locations[locations.index(here) + 1])
    while new[0] >= HEIGHT:
        webpage.line += HEIGHT
        new = subtract_height(HEIGHT, new)
        webpage.needs_redraw = True
    webpage.curpos = new

def backup_cursor(webpage):
    '''
    move cursor to previous link or form field
    '''
    locations = list(webpage.links.keys())
    here = add_height(webpage.line, WINDOW.getyx())
    logging.debug('here: %s, adjusted: %s', WINDOW.getyx(), here)
    new = subtract_height(webpage.line, locations[locations.index(here) - 1])
    while new[0] < 0:
        webpage.line -= HEIGHT
        new = add_height(HEIGHT, new)
        webpage.needs_redraw = True
    webpage.curpos = new

def activate(webpage):
    '''
    visit link at cursor, or submit current form
    '''
    here = tuple(add_height(webpage.line, WINDOW.getyx()))
    href = urlparse.urljoin(webpage.url, webpage.links[here])
    logging.debug('going to: %s', href)
    # truncate the Pages to just this one and those before it
    PAGES[STATE['urlindex'] + 1:] = []
    PAGES.append(Page(href))
    STATE['urlindex'] = -1

def previous_page(webpage):  #pylint: disable=unused-argument
    '''
    "backpage" -- backup through link chain
    '''
    index = STATE['urlindex']
    if index > 0:
        STATE['urlindex'] -= 1
        PAGES[index - 1].needs_refresh = True

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

def add_height(height, position):
    '''
    add height to position[0] and return adjusted tuple
    '''
    return position[0] + height, position[1]

def subtract_height(height, position):
    '''
    subtract height from position[0] and return adjusted tuple
    '''
    return [position[0] - height, position[1]]

if __name__ == '__main__':
    # action on invoking program directly rather than importing it
    init()
    if WINDOW:
        try:
            curses.wrapper(pyw, *sys.argv[1:])  # WINDOW is automatically passed
        except Exception:
            logging.exception("Program error")
            raise
    else:
        pyw(WINDOW, *sys.argv[1:])
