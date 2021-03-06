#!/usr/bin/env python2
# -*- coding: UTF-8 -*-

import sys, cStringIO, re
from BeautifulSoup import BeautifulSoup
from WebCursor import WebCursor
from pdfminer.pdfparser import PDFParser, PDFDocument
from pdfminer.converter import TextConverter
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter, \
        process_pdf
from pdfminer.cmapdb import CMapDB
from pdfminer.layout import LAParams
import datetime, pickle, textwrap, argparse
import os.path
import random

consolewidth = 79

default_encoding = sys.stdout.encoding
if default_encoding is None:
    default_encoding = 'utf-8'
loske_base_url = u"http://www.betriebsrestaurant-gmbh.de/"
loske_main = u"index.php?id=91"
mensa = \
    u"http://www.studentenwerk-muenchen.de/mensa/speiseplan/speiseplan_{0}_-de.html"
mensa_id = {"arcisstr": 421,
            "garching": 422}
config_file = os.path.expanduser(os.path.join(u"~", u".essen"))

mensa_price_mapping = {
    u"Tagesgericht 1"   : (1.00, 1.90, 2.40),
    u"Tagesgericht 2"   : (1.55, 2.20, 2.70),
    u"Tagesgericht 3"   : (1.90, 2.40, 2.90),
    u"Tagesgericht 4"   : (2.40, 2.80, 3.30),
    u"Biogericht 1"     : (1.55, 2.20, 2.70),
    u"Biogericht 2"     : (1.90, 2.40, 2.90),
    u"Biogericht 3"     : (2.40, 2.80, 3.30),
    u"Biogericht 4"     : (2.60, 3.00, 3.50),
    u"Biogericht 5"     : (2.80, 3.20, 3.70),
    u"Biogericht 6"     : (3.00, 3.40, 3.90),
    u"Biogericht 7"     : (3.20, 3.60, 4.10),
    u"Biogericht 8"     : (3.50, 3.90, 4.40),
    u"Biogericht 9"     : (4.00, 4.40, 4.90),
    u"Biogericht 10"    : (4.50, 4.90, 5.40),
    u"Aktionsessen 1"   : (1.55, 2.20, 2.70),
    u"Aktionsessen 2"   : (1.90, 2.40, 2.90),
    u"Aktionsessen 3"   : (2.40, 2.80, 3.30),
    u"Aktionsessen 4"   : (2.60, 3.00, 3.50),
    u"Aktionsessen 5"   : (2.80, 3.20, 3.70),
    u"Aktionsessen 6"   : (3.00, 3.40, 3.90),
    u"Aktionsessen 7"   : (3.20, 3.60, 4.10),
    u"Aktionsessen 8"   : (3.50, 3.90, 4.40),
    u"Aktionsessen 9"   : (4.00, 4.40, 4.90),
    u"Aktionsessen 10"  : (4.50, 4.90, 5.40)}

class bcolors:
    HEADER = ''
    OKBLUE = ''
    OKGREEN = ''
    WARNING = ''
    FAIL = ''
    ENDC = ''

    import platform
    if platform.system() == u'Linux':
        HEADER = '\033[95m'
        OKBLUE = '\033[94m'
        OKGREEN = '\033[92m'
        WARNING = '\033[93m'
        FAIL = '\033[91m'
        ENDC = '\033[0m'

    def disable(self):
        self.HEADER = ''
        self.OKBLUE = ''
        self.OKGREEN = ''
        self.WARNING = ''
        self.FAIL = ''
        self.ENDC = ''

TYPE_FMI, TYPE_IPP, TYPE_MENSA, TYPE_MENSA_XP = range(4)
type_translation = {"FMI": TYPE_FMI,
                    "IPP": TYPE_IPP,
                    "MEN": TYPE_MENSA,
                    "MXP": TYPE_MENSA_XP}

config = {}
config["last_update_ipp"] = datetime.date(1,1,1)
config["last_update_mensa"] = datetime.date(1,1,1)
config["last_update_fmi"] = datetime.date(1,1,1)
config["meals"] = {}

def error(string):
    print >>sys.stderr, string
    sys.exit(1)

def save_config(filename):
    fp = open(filename, "w")
    if fp:
        pickle.dump(config, fp)
    fp.close()

def load_config(filename):
    global config
    fp = open(filename, "r")
    if fp:
        config = pickle.load(fp)
    fp.close()

def filter_meals(date):
    for t, s in config["meals"][date]:
        if t in config["locations"]:
            yield t, s

def unicodewrap(string, width):
    # textwrap.wrap handles unicode non-breakable spaces incorrectly
    # so we need to encode before and decode after textwrap.wrap
    l = textwrap.wrap(string.encode('utf-8'), width)
    return [el.decode('utf-8') for el in l]

def dump_all_meals():
    dates = sorted(config["meals"].keys())
    for d in dates:
        print u"%s:" % (str(d)) 
        for m in filter_meals(d):
            t, s = m
            sb = u'\n       '.join(unicodewrap(s, consolewidth-7))
            if t is TYPE_IPP:
                print " IPP",
            elif t is TYPE_FMI:
                print " FMI",
            else:
                print " MEN",
            print "- %s" % (sb.encode(default_encoding, 'replace'))

def dump_one_day_meals(date):
    dates = config["meals"].keys()
    for d in dates:
        if d == date:
            print u"%s:" % (str(d)) 
            for m in filter_meals(d):
                t, s = m
                sb = u'\n       '.join(unicodewrap(s, consolewidth-7))
                if t is TYPE_IPP:
                    print " IPP",
                elif t is TYPE_FMI:
                    print " FMI",
                else:
                    print " MEN",
                print "- %s" % (sb.encode(default_encoding, 'replace'))
    if TYPE_MENSA_XP in config["locations"]:
        ex = extrapolationsgericht(date)
        if ex is not None:
            sb = u'\n       '.join(unicodewrap(ex, consolewidth-7))
            print " MXP",
            print "- %s" % (sb.encode(default_encoding, 'replace'))

def extrapolationsgericht(date):
    pricesplit_re = re.compile(u'(.*) (\(.*\))', re.UNICODE)
    mealsplit_re = re.compile(u'(.*) (an|mit|in|vom|auf) (.*)', re.IGNORECASE |
                                                                re.UNICODE)
    mealsplit_pseudo_re = re.compile(u'.* (".*"|all .*).*', re.IGNORECASE |
                                                            re.UNICODE)
    mealsplit_pseudo1_re = re.compile(u'(.*) (".*"|all .*).*', re.IGNORECASE | 
                                                               re.UNICODE)
    yesterday = date - datetime.timedelta(days=1)
    # skip weekend
    while yesterday.weekday() == 6 or yesterday.weekday() == 5:
        yesterday -= datetime.timedelta(days=1)
    dates = config["meals"].keys()
    meals = []
    for d in dates:
        if d == yesterday:
            for m in filter_meals(d):
                t,s = m
                if t is not TYPE_IPP and t is not TYPE_FMI:
                    meals.append(s)
    meals_split = []
    prices = []
    for m in meals:
        ret = pricesplit_re.search(m)
        if ret:
            name, price = ret.groups()
            meals_split.append(name)
            prices.append(price)

    firsts = []
    middles = []
    lasts = []

    for m in meals_split:
        ret1 = mealsplit_re.search(m)
        ret2 = mealsplit_pseudo_re.search(m)
        ret3 = mealsplit_pseudo1_re.search(m)
        if ret1:
            g = ret1.groups()
            firsts.append(g[0])
            middles.append(g[1])
            lasts.append(g[2])
        if ret2:
            lasts.append(ret2.groups()[0])
        if ret3:
            firsts.append(ret3.groups()[0])
    
    if len(firsts) < 1 or len(middles) < 1 or len(lasts) < 1:
        return None

    return u'%s %s %s %s' % (random.choice(firsts),
                             random.choice(middles),
                             random.choice(lasts),
                             random.choice(prices))

def show_last_update():
    print u"ipp: %s, mensa: %s" % (str(config["last_update_ipp"]),
                                   str(config["last_update_mensa"]))

def remove_older(when):
    for k in config["meals"].keys():
        if k < when:
            del config["meals"][k]

def parse_loske_pdf(pdf, is_ipp=True):
    stripcid_re = re.compile(u"\(cid:.*?\)", re.UNICODE)
    newline_heuristic_re = re.compile(u"Montag, den |Dienstag, den |Mittwoch" \
                                      u", den |Donnerstag, den |Freitag, den ",
                                      re.IGNORECASE | re.UNICODE)
    bnw_endheuristic_re = re.compile(u"B\.n\.W\.=Beilage.*", re.UNICODE)
    dow_beginheuristic_re = re.compile(u".*?Montag, den ",
                                       re.IGNORECASE | re.UNICODE)
    meal_detect_re = re.compile(u"(\d\.)(.*?)(\d)\.(\d\d)", re.UNICODE)
    #meal_detect_re = re.compile(u"(\d\.)(\D)", re.UNICODE)
    date_re = re.compile(u"(\d{1,2})\.(\d{1,2})\.(\d{1,4})(.*)", re.UNICODE)
    meal_props = re.compile(ur'\b[VKRS](?:\+[VKRS])*\b\s*', re.UNICODE)
    meal_numbers = re.compile(ur'([^/]|^)\s*\b[1-6](?:,[1-6])*\b([^/]|$)',
                              re.UNICODE)

    rsrcmgr = PDFResourceManager()
    outtxt = cStringIO.StringIO()
    device = TextConverter(rsrcmgr, outtxt)
    
    pdfp = PDFParser(cStringIO.StringIO(pdf))
    doc = PDFDocument()
    pdfp.set_document(doc)
    doc.set_parser(pdfp)
    doc.initialize("")

    if not doc.is_extractable:
        print >>sys.stderr, u"PDF Document not extractable"
        sys.exit(1)

    interpreter = PDFPageInterpreter(rsrcmgr, device)
    for (pageno,page) in enumerate(doc.get_pages()):
        #print pageno
        interpreter.process_page(page)
    
    device.close()

    fulltext = outtxt.getvalue().decode('utf-8', 'replace')
    fulltext = stripcid_re.sub(u'', fulltext)
    fulltext = dow_beginheuristic_re.sub(u'', fulltext)
    fulltext = bnw_endheuristic_re.sub(u'', fulltext)
    fulltext = newline_heuristic_re.sub(u'\n', fulltext)

    lines = fulltext.split(u'\n')

    now = datetime.date(1,1,1)

    for line in lines:
        ret = date_re.search(line)
        if ret:
            day, month, year, meals = ret.groups()
            try:
                now = datetime.date(int(year), int(month), int(day))
            except ValueError:
                # some weird date in pdf (like 29.02.2013), skipping these
                # entries is the easiest solution
                continue
            #meals = meal_detect_re.sub(ur'\n\2(\3.\4 €)', meals).strip()
            meals = meal_detect_re.finditer(meals)
            for meal_match in meals:
                m = meal_match.group(2)
                m = meal_props.sub(u'', m)
                m = meal_numbers.sub(lambda x : x.group(1) + x.group(2), m)
                m = m.replace(u'*', u'')
                m = m.split()
                m.append(u'({0}.{1} €)'.format(meal_match.group(3),
                                               meal_match.group(4)))
                m = u' '.join(m)
                meal_type = TYPE_IPP if is_ipp else TYPE_FMI
                try:
                    tmp = config["meals"][now]
                    config["meals"][now].append((meal_type, m))
                except KeyError, e:
                    config["meals"][now] = [(meal_type, m)]

def get_new_loske(is_ipp=True):
    wc = WebCursor();
    loske_html = wc.get(loske_base_url+loske_main)
    if loske_html == "":
        print >>sys.stderr, u"Could not download" , loske_base_url+loske_main
        sys.exit(1)
    soup = BeautifulSoup(loske_html)
    # print soup.prettify()
    tables = soup.findAll(u'table', attrs={u'class' : u'csc-uploads csc-uploads-0'})
    thisweek_url = ""
    if len(tables) < 2:
        print >>sys.stderr, u"Parse html error"
        sys.exit(1)
    # First table is IPP, third table is FMI
    table = tables[0] if is_ipp else tables[2]
    alla = table.findAll('a')
    if len(alla) < 1:
        print >>sys.stderr, u"Parse html error"
        sys.exit(1)
    thisweek_url = alla[0]['href']
    if thisweek_url == "":
        print >>sys.stderr, u"Parse html error"
        sys.exit(1)

    pdf = wc.get(loske_base_url+thisweek_url)
    if pdf == "":
        print >>sys.stderr, u"Could not download", loske_base_url+thisweek_url
        sys.exit(1)
    parse_loske_pdf(pdf, is_ipp)

    nextweek_url = ""
    # Second table is IPP, fourth table is FMI
    if len(tables) == 4:
        table = tables[1] if is_ipp else tables[3]
        alla = table.findAll('a')
        if len(alla) < 1:
            print >>sys.stderr, u"Parse html error"
            sys.exit(1)
        nextweek_url = alla[0]['href']
        if thisweek_url == "":
            print >>sys.stderr, u"Parse html error"
            sys.exit(1)

        pdf = wc.get(loske_base_url+nextweek_url)
        if pdf == "":
            print >>sys.stderr, u"Could not download", loske_base_url+nextweek_url
            sys.exit(1)
        parse_loske_pdf(pdf, is_ipp)

    config["last_update_ipp"] = datetime.date.today()

def dow_to_int(dow):
    montag_re = re.compile(u"Montag", re.IGNORECASE | re.UNICODE)
    dienstag_re = re.compile(u"Dienstag", re.IGNORECASE | re.UNICODE)
    mittwoch_re = re.compile(u"Mittwoch", re.IGNORECASE | re.UNICODE)
    donnerstag_re = re.compile(u"Donnerstag", re.IGNORECASE | re.UNICODE)
    freitag_re = re.compile(u"Freitag", re.IGNORECASE | re.UNICODE)

    ret = montag_re.search(dow)
    if ret:
        return 0
    ret = dienstag_re.search(dow)
    if ret:
        return 1
    ret = mittwoch_re.search(dow)
    if ret:
        return 2
    ret = donnerstag_re.search(dow)
    if ret:
        return 3
    ret = freitag_re.search(dow)
    if ret:
        return 4

    return -1

def get_new_mensa():
    date_re = re.compile(u".., (\d{1,2})\.(\d{1,2})\.(\d{1,4})", re.UNICODE)
    desc_nl_re = re.compile(u"(?:(.*?)(?:<br>))*", re.UNICODE)
    desc_nl_rep_re = re.compile(u"<br>", re.UNICODE)
    foodtags_re = re.compile(
        ur"(?:\s*\([0-9vfSR][0-9]?(?:,[0-9vfSR][0-9]?)*\))", re.UNICODE)

    wc = WebCursor();
    mensa_url = mensa.format(mensa_id[config["mensa_location"]])
    mensa_html = wc.get(mensa_url)
    if mensa_html == "":
        print >>sys.stderr, u"Could not download" , mensa_url
        sys.exit(1)
    soup = BeautifulSoup(mensa_html)
    
    days = soup.findAll(u"table", attrs={u"class": u"menu"})
    for d in days:
        headline = d.findAll(u"td", attrs={u"class": u"headline"})
        if len(headline) < 2:
            error("Mensa parse error.")
        headline = headline[1]
        strhl = headline.findAll(u"strong")
        if len(strhl) < 1:
            error("Mensa parse error.")
        ret = date_re.search(strhl[0].text)
        if not ret:
            error("Mensa parse error.")
        day, month, year = ret.groups()
        now = datetime.date(int(year), int(month), int(day))
        
        meals = d.findAll(u"tr")
        for m in meals:
            if len(m.findAll(u"td", attrs={u"class": u"headline"})) > 0:
                continue
            typ = m.findAll(u"td", attrs={u"class": u"gericht"})
            if len(typ) < 1:
                error("Mensa parse error.")
            price = None
            for match, value in mensa_price_mapping.items():
                ret = re.search(match, typ[0].text)
                if ret:
                    price = value[config["person"]]
                    break
            
            desc = m.findAll(u"td", attrs={u"class": u"beschreibung"})
            if len(desc) < 1:
                error("Mensa parse error.")
            desc = desc[0].findAll(u"span", attrs={u"style": u"float:left"})
            if len(desc) < 1:
                error("Mensa parse error.")

            t = desc[0].text
            t = t.strip()
            t = foodtags_re.sub(u'', t)
            t = re.sub(r'[Z|z]igeuner', u"Südländer Typ II", t)
            t = t.split()
            if price is not None:
                t.append(u"(%.2f €)" % (price,))
            t = ' '.join(t)

            try:
                tmp = config["meals"][now]
                config["meals"][now].append((TYPE_MENSA, t))
            except KeyError, e:
                config["meals"][now] = [(TYPE_MENSA, t)]

    config["last_update_mensa"] = datetime.date.today()

def update_all():
    print >>sys.stderr, u"Updating..."
    config["meals"] = {}
    if TYPE_MENSA in config["locations"]:
        get_new_mensa()
    if TYPE_IPP in config["locations"]:
        get_new_loske(is_ipp=True)
    if TYPE_FMI in config["locations"]:
        get_new_loske(is_ipp=False)
    save_config(config_file)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=textwrap.dedent('''\
    Command line interface to the Mensa, Max-Planck-Institute Garching
     and FMI Garching.
        DATE can be a date in german format (e.g. 14.04.2011, 4.2.2010, ...)
        DATE can also be a day and month (e.g. 14.4.)
        DATE can also be only a day, month and year will be the current year 
              and month
        You can also specify a german weekday (e.g. Montag or mo)
        If date is 'all' then all saved meals are displayed, 'morgen' displays
              the meal of the next day
'''),
            epilog='Warning! Extremely hacky software!')

    def is_a_date(string):
        date_re = re.compile(u'(\d{1,2})\.(\d{1,2})\.(\d{1,4})', re.UNICODE)
        shortdate_re = re.compile(u'(\d{1,2})\.(\d{1,2})', re.UNICODE)
        day_re = re.compile(u'(mo|di|mi|do|fr|sa|so|Montag|Dienstag|Mittwoch' \
                            u'|Donnerstag|Freitag|Samstag|Sonntag)',
                            re.IGNORECASE | re.UNICODE)
        daynum_re = re.compile(u'(\d{1,2})', re.UNICODE)
        all_re = re.compile(u'all', re.IGNORECASE | re.UNICODE)
        morgen_re = re.compile(u'morgen', re.IGNORECASE | re.UNICODE)
        matched = False
        ret = None    

        r = date_re.search(string)
        if r:
            day, month, year = r.groups()
            ret = datetime.date(int(year), int(month), int(day))
            return ret

        r = shortdate_re.search(string)
        if r:
            day, month = r.groups()
            ret = datetime.date(datetime.date.today().year,
                                int(month), int(day))
            return ret

        r = daynum_re.search(string)
        if r:
            day = r.groups()[0]
            ret = datetime.date(datetime.date.today().year,
                                datetime.date.today().month, int(day))
            return ret
        
        r = all_re.search(string)
        if r:
            ret = "all"
            return ret

        r = morgen_re.search(string)
        if r:
            ret = datetime.date.today() + datetime.timedelta(1)
            return ret

        r = day_re.search(string)
        if r:
            wd = r.groups()[0].lower()
            dowint = 0
            if wd[:2] == "mo":
                dowint = 0
            elif wd[:2] == "di":
                dowint = 1
            elif wd[:2] == "mi":
                dowint = 2
            elif wd[:2] == "do":
                dowint = 3
            elif wd[:2] == "fr":
                dowint = 4
            elif wd[:2] == "sa":
                dowint = 5
            else:
                dowint = 6

            ret = datetime.date.today()
            for i in range(7):
                if ret.weekday() == dowint:
                    break
                else:
                    ret += datetime.timedelta(days=1)
            return ret
                
        if not ret:
            msg = u"%s is not a valid date, day of week (german) or 'all'" \
                    % (string,)
            raise argparse.ArgumentTypeError(msg)

        return ret

    parser.add_argument('-u', action='store_true', default=False,
                        help='Update the database')
    parser.add_argument('-p', dest='person', default='',
                        help="Personal status (student|employee|guest)")
    parser.add_argument('--ml', dest='mensa_location', choices=mensa_id.keys(),
                        help="Choose your mensa location")
    parser.add_argument('-l', '--locations', metavar="L1:L2:...",
                        help="Locations to print " \
                        "({0})".format('|'.join(type_translation.keys())))
    parser.add_argument('--na', '--no-autoupdate', dest='autoupdate',
                        default=True, action='store_false',
                        help="Disable autoupdate (useful when no internet "
                        "connection is available)")
    parser.add_argument('date', 
            metavar='DATE', 
            nargs='?',
            type=is_a_date,
            help='Lookup meals for specific date')

    opts = parser.parse_args()

    if os.path.isfile(config_file):
        load_config(config_file)
    elif not opts.u:
        print >>sys.stderr, bcolors.FAIL + "No configfile found.\n" + \
                bcolors.ENDC + "You need to update and perform basic " \
                "setup.\nFor example if you are a student in Garching run:\n" \
                + sys.argv[0] + " -u -p student --ml garching -l MEN:IPP\n" \
                "See " + sys.argv[0] + " -h for more info"
        sys.exit(1)

    if opts.person:
        if opts.person == "student":
            config["person"] = 0
        elif opts.person == "employee":
            config["person"] = 1
        elif opts.person == "guest":
            config["person"] = 2
        else:
            print >>sys.stderr, bcolors.FAIL + "Unknown option given to " \
                    "-p" + bcolors.ENDC
            sys.exit(1)

    if opts.mensa_location:
        config["mensa_location"] = opts.mensa_location

    if opts.locations:
        config["locations"] = [type_translation[l] for l in \
                               opts.locations.split(':') \
                               if l in type_translation]
        save_config(config_file)

    if "person" not in config:
        config["person"] = 0
    if "mensa_location" not in config:
        config["mensa_location"] = "arcisstr"
    if "locations" not in config:
        config["locations"] = type_translation.values()
        save_config(config_file)

    if opts.u or opts.person or opts.mensa_location:
        update_all()

    current_week = datetime.date.today().isocalendar()[1]
    try:
        if (opts.autoupdate and
            ((current_week != config["last_update_mensa"].isocalendar()[1] and
              TYPE_MENSA in config["locations"]) or
             (current_week != config["last_update_ipp"].isocalendar()[1] and
              TYPE_IPP in config["locations"]) or
             (current_week != config["last_update_fmi"].isocalendar()[1] and
              TYPE_FMI in config["locations"]))):
            do_update = True
    except KeyError:
       do_update = True 

    if do_update:
        print >>sys.stderr, (bcolors.WARNING + "Last update was not in this "
                "week." + bcolors.ENDC)
        update_all()

    if opts.date is None:
        dump_one_day_meals(datetime.date.today())
        sys.exit(0)

    if opts.date == "all":
        dump_all_meals()
        sys.exit(0)

    dump_one_day_meals(opts.date)
