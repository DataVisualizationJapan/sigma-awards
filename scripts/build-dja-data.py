#!/usr/bin/env python3
"""Build the DJA catalog exclusively from the supplied HTML archive. No network I/O."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from dja.html_tree import Node, Tree, clean
from dja.thumbnails import ancestor, attach_thumbnails, image_urls

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / 'data-journalism-awards' / 'archive'
PATCHES = ROOT / 'scripts' / 'dja' / 'corrections.json'
RANK = {'winner': 0, 'mention': 1, 'shortlist': 2}
COUNTRIES = {'USA': 'United States', 'US': 'United States', 'U.S.': 'United States', 'UK': 'United Kingdom',
             'Russian Federation': 'Russia', 'mainland China': 'China', 'globally': 'International',
             'United States of America': 'United States'}
KNOWN_COUNTRIES = set(COUNTRIES) | set(COUNTRIES.values()) | {
    'Argentina', 'Australia', 'Austria', 'Afghanistan', 'Belgium', 'Bolivia', 'Brazil', 'Bulgaria', 'Canada',
    'Chile', 'China', 'Colombia', 'Costa Rica', 'Cuba', 'Denmark', 'Egypt', 'Finland', 'France', 'Germany',
    'Ghana', 'Greece', 'Hong Kong', 'Hungary', 'India', 'Indonesia', 'Ireland', 'Israel', 'Italy', 'Japan',
    'Kenya', 'Lebanon', 'Macedonia', 'Malaysia', 'Mexico', 'Mongolia', 'Nepal', 'Netherlands', 'New Zealand',
    'Nigeria', 'Norway', 'Pakistan', 'Panama', 'Peru', 'Philippines', 'Poland', 'Portugal', 'Puerto Rico',
    'Qatar', 'Romania', 'Serbia', 'Singapore', 'Slovakia', 'South Africa', 'South Korea', 'Spain', 'Sweden',
    'Switzerland', 'Taiwan', 'Tanzania', 'Tunisia', 'Turkey', 'Uganda', 'Ukraine', 'United Arab Emirates',
    'Uruguay', 'Venezuela', 'Vietnam', 'Bosnia and Herzegovina', 'Puerto Rico, United States'}


def key(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    return ''.join(c for c in text if c.isalnum() and not unicodedata.combining(c))


def url_clean(url, base=''):
    url = urljoin(base, clean(url))
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.netloc:
        return ''
    query = [(k, v) for k, vs in parse_qs(p.query).items() if not k.startswith('utm_') for v in vs]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), p.fragment))


def url_key(url):
    p = urlsplit(url)
    host = p.netloc.lower().removeprefix('www.').replace('guardian.co.uk', 'theguardian.com')
    return host + p.path.rstrip('/') + ('?' + p.query if p.query else '')


def is_profile(url):
    host = urlsplit(url).netloc.lower()
    return any(s in host for s in ('datajournalismawards.org', 'globaleditorsnetwork.org', 'wizehive.com'))


def kind_for(category):
    c = category.casefold()
    if 'individual' in c and 'portfolio' in c:
        return 'portfolio'
    if 'team' in c or 'newsroom portfolio' in c:
        return 'team'
    if 'student' in c or 'young data journalist' in c:
        return 'individual'
    if ('website' in c or 'section' in c) and 'application' not in c and 'app' not in c:
        return 'site'
    return 'project'


def category_clean(text):
    text = re.sub(r'\s*\[\s*link[^]]*\]', '', text, flags=re.I)
    return clean(re.sub(r'^(?:Category\s*)?\d+[.:]\s*', '', text, flags=re.I)).rstrip(': *')


def country_tail(text):
    text = clean(text).strip(' ,;()')
    for country in sorted(KNOWN_COUNTRIES, key=len, reverse=True):
        if text.casefold() == country.casefold():
            return '', COUNTRIES.get(country, country)
        if text.casefold().endswith(', ' + country.casefold()):
            return text[:-(len(country)+2)].strip(' ,'), COUNTRIES.get(country, country)
    return text, ''


def named(text, anchor=None):
    text = clean(text).lstrip('- ').strip()
    if anchor and anchor.text and text.startswith(anchor.text):
        title = anchor.text
        tail = text[len(title):].strip(' ,')
        org, country = country_tail(tail)
        if not tail:
            body, country = country_tail(title)
            if country:
                title, _, org = body.rpartition(', ')
                if not title:
                    title, org = body, ''
        elif country and not org and ', ' in title:
            title, org = title.rsplit(', ', 1)
        return title.strip(' “”.'), org, country
    body, country = country_tail(text)
    if ', ' in body:
        title, org = body.rsplit(', ', 1)
    else:
        title, org = body, ''
    return title.strip(' “”.'), org, country


def line_blocks(node):
    """Text and links per visual line, including br-delimited 2016 records."""
    text, links = [], []
    out = []
    blocks = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'li', 'tr'}
    def flush():
        value = clean(''.join(text))
        if value:
            out.append((value, list(links)))
        text.clear(); links.clear()
    def walk(n):
        if isinstance(n, str):
            text.append(n); return
        if n.tag in ('script', 'style', 'noscript'):
            return
        if n.tag in blocks or n.tag == 'br':
            flush()
        if n.tag == 'a' and n.attrs.get('href'):
            links.append(n)
        for c in n.children:
            walk(c)
        if n.tag in blocks:
            flush()
    walk(node); flush()
    return out


class Catalog:
    def __init__(self, source):
        self.source = source
        self.manifest = json.loads((source/'manifest.json').read_text())
        self.sources = {p['file']: p for p in self.manifest['pages']}
        self.trees = {str(p.relative_to(source)): Tree(p.read_text(encoding="utf-8", errors="replace")).root for p in sorted(source.rglob('*.html'))}
        self.rows = []
        self.supplements = []
        self.stats = []
        self.patches = json.loads(PATCHES.read_text())
        self.used_patches = set()

    def provenance(self, file):
        info = self.sources.get(file)
        if info:
            return {'file': file, 'original': info['original'], 'wayback': info['wayback']}
        parent = re.sub(r'-page-?\d+(?=\.html)', '', file)
        if '/wizehive-pages/' in file:
            parent = '2013/wizehive-pages/page-1.html'
        info = self.sources.get(parent, {})
        # Extra saved pages have no individual snapshot timestamp in the manifest.
        return {'file': file, 'original': info.get('original', ''), 'wayback': '', 'groupFile': parent}

    def add(self, file, year, title, category, result='shortlist', org='', country='', links=(), summary='', jury='', raw='', images=(), supplement=False):
        title = clean(title)
        if not title:
            raise ValueError(f'Empty title: {file}: {raw}')
        src = self.provenance(file)
        clean_links = list(dict.fromkeys(u for x in links if (u := url_clean(x, src['original']))))
        row = {'year': year, 'title': title, 'org': clean(org), 'country': country,
               'category': category_clean(category), 'result': result, 'links': clean_links,
               'summary': clean(summary), 'jury': clean(jury), 'source': src,
               'sourceText': clean(raw), 'imageSources': list(images)}
        (self.supplements if supplement else self.rows).append(row)
        return row

    def nominees_2012(self):
        file = '2012/nominees.html'; category = ''
        for tr in self.trees[file].nodes('tr'):
            strong = tr.first('strong')
            if strong and 'data' in strong.text.lower():
                category = strong.text
            for li in tr.nodes('li'):
                a = li.first('a')
                if category and a:
                    title, org, country = named(li.text, a)
                    self.add(file, 2012, title, category, org=org, country=country, links=[a.attrs['href']], raw=li.text)

    def winners_2012(self):
        file='2012/winners.html'; category=sub=''; result='winner'
        nodes=list(self.trees[file].nodes())
        for i, n in enumerate(nodes):
            if n.tag=='h1' and re.match(r'^\d\.', n.text):
                category=category_clean(n.text)
            elif n.tag=='h1' and 'HONORABLE' in n.text:
                result='mention'
            elif n.tag=='h4': sub=n.text
            elif result=='mention' and n.tag=='h2':
                category=category_clean(n.text); sub=''
            elif n.tag=='h3' and category and n.first('a'):
                a=n.first('a'); title=a.text
                tail=n.text[len(title):].strip(' ()')
                org,country=country_tail(tail)
                end=next((x.pos for x in nodes[i+1:] if x.tag in ('h1','h2','h3','h4')),999999)
                jury=' '.join(x.text for x in nodes[i+1:] if x.pos<end and x.tag=='blockquote')
                self.add(file,2012,title,category + (', '+sub if sub else ''),result,org,country,[a.attrs['href']],jury=jury,raw=n.text)

    def shortlist_2013(self):
        for file, tree in self.trees.items():
            if not file.startswith('2013/wizehive-pages/'):
                continue
            tabs={n.attrs.get('id','').removeprefix('vtab'):n.text for n in tree.nodes('a') if n.attrs.get('id','').startswith('vtab')}
            for item in tree.nodes('div','item'):
                title_node=next((n for n in item.nodes('div') if n.has_class('field424763')),None)
                org_node=next((n for n in item.nodes('div') if n.has_class('field424748')),None)
                if not title_node: continue
                a=title_node.first('a')
                cats=[tabs[c.removeprefix('tab')] for c in item.attrs.get('class','').split() if c.startswith('tab') and c != 'tab13447' and c.removeprefix('tab') in tabs]
                self.add(file,2013,title_node.text,cats[0] if cats else '',org=org_node.text if org_node else '',links=[a.attrs['href']] if a else [],raw=title_node.text,
                         images=[im.attrs['src'] for im in item.nodes('img') if 'media' not in im.attrs.get('alt','').lower() and im.attrs.get('width')=='175'])

    def winners_2013(self):
        file='2013/winners.html'
        for td in self.trees[file].nodes('td'):
            ps=list(td.nodes('p'))
            if len(ps)<3 or not re.match(r'Data[- ]',ps[0].text,re.I): continue
            cat=ps[0].text.rstrip(':* ')
            raw=ps[1].text
            m=re.search(r'^(.*?)\s+for\s+(?:the\s+)?[“\"](.*?)[”\"]',raw,re.I)
            if m:
                org,title=m.groups()
            else:
                org,title=raw.split(' for ',1)
                title=title.split(', on the pay gap')[0]
            a=ps[2].first('a')
            row=self.add(file,2013,title.rstrip('.'),cat,'winner',org.rstrip(', '),'',[a.attrs['href']] if a else [],summary=ps[2].text,raw=td.text)
            if 'People’s Choice Award' in td.text:
                self.add(file,2013,row['title'],"People’s Choice Award",'winner',row['org'],links=row['links'],raw=td.text)
            if 'The Wealth of the Gods of Faura' in td.text:
                self.add(file,2013,'The Wealth of the Gods of Faura',cat,'mention','The Philippine Center for Investigative Journalism','Philippines',raw=td.text)

    def winners_2015(self):
        # Contemporary winner descriptions supplement the retrospective summary.
        file='2015/winners.html'
        nodes=list(self.trees[file].nodes())
        for i,n in enumerate(nodes):
            if n.tag!='h3' or not (n.text.startswith('Category ') or n.text=='Special Citation'):continue
            end=next((x.pos for x in nodes[i+1:] if x.tag=='h3'),999999)
            block_ps=[x for x in nodes[i+1:] if x.pos<end and x.tag=='p']
            ps=[x for x in block_ps if x.text]
            raw=' '.join(p.text for p in ps)
            category=category_clean(n.text)
            if 'Open Data Award' in category:
                titles=['#Tracked','Treatment Tracker']
            elif 'General Excellence' in category:titles=['Al Jazeera America — General Excellence']
            elif 'Individual Portfolio' in category:titles=['Rob Barry']
            elif 'Investigation of the Year (Large' in category:titles=['Swiss Leaks / Luxembourg Leaks']
            else:
                m=re.search(r'for [“\"]([^”\"]+)[”\"]',raw)
                titles=[m[1]] if m else []
            for title in titles:
                self.add(file,2015,title,category,raw=raw,images=[u for p in block_ps for u in image_urls(p,self.provenance(file)['original'])][:1] if len(titles)==1 else [],supplement=True)

    def shortlist_2014(self):
        file='2014/shortlist.html'; category=''
        for tr in self.trees[file].nodes('tr'):
            cells=[c for c in tr.children if isinstance(c,Node) and c.tag=='td']
            if len(cells)==1 and re.match(r'\d\.',cells[0].text):
                category=category_clean(cells[0].text)
            elif len(cells)==4 and category:
                self.add(file,2014,cells[0].text,category,org=cells[1].text,country=COUNTRIES.get(cells[2].text,cells[2].text),
                         links=[a.attrs['href'] for a in cells[3].nodes('a') if 'href' in a.attrs],raw=' | '.join(c.text for c in cells))

    def past_winners(self):
        file='2018/past-winners.html'; year=None; category=''
        for n in self.trees[file].nodes():
            if n.tag=='h2':
                m=re.search(r'Data Journalism Awards (201[4-7]) winning projects',n.text)
                if m: year=int(m[1]); category=''
                elif year and n.text: category=n.text
            elif n.tag=='h4' and year and category and n.text:
                text=n.text; org=''; title=text
                if ' for ' in text: org,title=text.split(' for ',1)
                elif ' from ' in text: title,org=text.split(' from ',1)
                elif (m:=re.match(r'(.+?)\s*\(([^)]+)\)$',text)): title,org=m.groups()
                a=n.first('a')
                self.add(file,year,title.strip(' “”“\"'),category,'mention' if 'honorable' in category.lower() or 'citation' in category.lower() else 'winner',org,
                         links=[a.attrs['href']] if a else [],raw=text)
        # The contemporary page retains the public-choice award omitted from past-winners.
        file='2014/winners.html'
        for li in self.trees[file].nodes('li'):
            if li.text.startswith("Public's Choice -"):
                self.add(file,2014,'The New York Times',"Public’s Choice",'winner','The New York Times',raw=li.text)

    def shortlist_2016(self):
        file='2016/shortlist.html'
        main=self.trees[file].first('section','main_content'); category=''
        for text, anchors in line_blocks(main):
            if re.match(r'^\d+\. ',text): category=category_clean(text); continue
            if not category or not anchors or not any('community.globaleditorsnetwork.org' in a.attrs['href'] for a in anchors): continue
            title_org=re.sub(r'\s*\[\s*link[^]]*\]', '',text,flags=re.I).lstrip('- ').strip()
            if title_org.endswith(')') and '(' in title_org:
                title,tail=title_org.split(' (',1); org,country=country_tail(tail.rstrip(')'))
            else:
                title,org,country=named(title_org)
            self.add(file,2016,title,category,org=org,country=country,links=[a.attrs['href'] for a in anchors],raw=text)

    def shortlist_recent(self,year,file=None):
        file=file or f'{year}/shortlist.html'; category=''
        for n in self.trees[file].nodes():
            if year in (2017,2018) and n.tag==('h3' if file.endswith('-gen.html') else 'h2'):
                category=n.text if not n.has_class('site__title') else ''
            if year==2019 and n.tag=='p' and n.first('strong') and not n.first('a') and n.text==n.first('strong').text:
                category=n.text
            if n.tag=='p' and category:
                anchors=[a for a in n.nodes('a') if a.attrs.get('href') and any(s in a.attrs['href'] for s in ('/node/','/projects/','project_id='))]
                if not anchors: continue
                a=anchors[0];title,org,country=named(n.text,a)
                self.add(file,year,title,category,org=org,country=country,links=[a.attrs['href']],raw=n.text)

    def winners_2018(self):
        file='2018/winners.html';category=''
        for n in self.trees[file].nodes():
            if n.tag=='h3': category=n.text
            elif n.tag=='p' and category and not category.startswith(('The Jury','Here is','Additionally')):
                # Each result starts with a linked title; the following text is jury commentary.
                a=next((a for a in n.nodes('a') if 'project_id=' in a.attrs.get('href','') or (category.endswith('public choice') and a.attrs.get('href','').startswith('https://g1.globo.com/'))),None)
                if not a: continue
                title,org,country=named(a.text,a)
                result='mention' if 'Honorable Mention' in n.text else 'winner'
                jury=n.text.split(a.text,1)[-1].strip()
                row=ancestor(n,'row')
                primary=next((link for link in row.nodes('a') if 'project_id=' in link.attrs.get('href','') or link.attrs.get('href','').startswith('https://g1.globo.com/')),None) if row else None
                images=image_urls(row,self.provenance(file)['original']) if primary is a else []
                self.add(file,2018,title,category,result,org,country,[a.attrs['href']],jury=jury,raw=n.text,images=images)
        # Citation records share one paragraph with prose instead of result cards.
        for p in self.trees[file].nodes('p'):
            if 'ExtraPol is an innovative' in p.text:
                for a in p.nodes('a'):
                    if a.text:
                        self.add(file,2018,a.text,'Citation for Excellence','mention',links=[a.attrs['href']],raw=p.text)

    def winners_2019(self):
        file='2019/winners.html'; nodes=list(self.trees[file].nodes())
        for i,n in enumerate(nodes):
            if n.tag!='h2' or not re.match(r'^(Winner|Honorable Mention):',n.text):continue
            previous=[x for x in nodes[:i] if x.tag=='p' and x.text]
            cat=previous[-1].text
            end=next((x.pos for x in nodes[i+1:] if x.tag=='h2'),999999)
            ps=[x for x in nodes[i+1:] if x.pos<end and x.tag=='p' and x.text]
            org=next((p.text.split(':',1)[1].strip() for p in ps if p.text.startswith('Organisation:')),'')
            country=next((p.text.split(':',1)[1].strip() for p in ps if p.text.startswith('Country/area:')),'')
            jury=[];started=False
            for p in ps:
                if p.text.startswith('Jury’s comment:'):started=True
                if started: jury.append(p.text.removeprefix('Jury’s comment:').strip())
                if p.text=='':break
            # Final paragraph before the next h2 is that next record's category.
            if jury and ps and not ps[-1].text.startswith('Jury’s comment:') and ps[-1].first('strong') and ps[-1].text==ps[-1].first('strong').text:
                jury=jury[:-1]
            a=n.first('a')
            self.add(file,2019,n.text.split(':',1)[1],cat,'mention' if n.text.startswith('Honorable') else 'winner',org,COUNTRIES.get(country,country),
                     [a.attrs['href']] if a else [],jury=' '.join(jury),raw=n.text+' | '+' | '.join(p.text for p in ps[:2]),
                     images=list(dict.fromkeys(u for p in n.parent.nodes('p') if n.pos<p.pos<end for u in image_urls(p,self.provenance(file)['original']))))

    def community(self):
        for file,tree in self.trees.items():
            if 'community-selected' not in file: continue
            year=int(file[:4])
            for item in tree.nodes('div','views-row'):
                title_node=item.first('div','views-field-title')
                if not title_node:continue
                a=title_node.first('a')
                desc=item.first('div','views-field-field-short-description')
                country=item.first('div','views-field-field-country')
                summary=desc.text if desc else ''
                # Preserve line breaks to separate category metadata from the actual description.
                desc_lines=[clean(s) for s in desc.raw_text().split('\n') if clean(s)] if desc else []
                category=desc_lines[0] if desc_lines and (desc_lines[0].startswith('Category ') or desc_lines[0] in ('Special Citation','Public Choice')) else ''
                if category:summary=clean(' '.join(desc_lines[1:]))
                flags=[n.text for n in item.nodes('div','field-content')]
                result='mention' if category=='Special Citation' else 'winner' if 'winner' in flags else 'shortlist' if 'finalist' in flags else ''
                self.add(file,year,title_node.text,category,result or 'shortlist',country=country.text.removeprefix('Country:').strip() if country else '',
                         links=[a.attrs['href']] if a else [],summary=summary,raw=title_node.text,
                         images=[url_clean(im.attrs.get('src',''),self.provenance(file)['original']) for im in item.nodes('img')],supplement=True)
                # Explicit flags, rather than the gallery title, establish selection status.
                if result:self.rows.append(dict(self.supplements[-1]))

    def listings(self):
        file='2018/project-listing.html'
        for picture in self.trees[file].nodes('div','project-picture'):
            card=picture.parent
            blocks=list(line_blocks(card))
            texts=[t for t,_ in blocks]
            a=picture.first('a')
            if not a or not texts:continue
            title=texts[0]
            country=next((t.removeprefix('Country:').strip() for t in texts if t.startswith('Country:')),'')
            org=next((t.removeprefix('Organisation:').strip() for t in texts if t.startswith('Organisation:')),'')
            self.add(file,2018,title,'',org=org,country=country,links=[a.attrs['href']],raw=card.text,images=image_urls(picture,self.provenance(file)['original']),supplement=True)
        for file in ['2019/projects.html','2019/projects-page-2.html','2019/projects-page-3.html']:
            for card in self.trees[file].nodes('div','col-project__content'):
                heading=card.first('h3')
                a=heading.first('a') if heading else None
                if not a:continue
                ps=[p.text for p in card.nodes('p') if p.text]
                self.add(file,2019,heading.text,'',links=[a.attrs['href']],summary=ps[-1] if ps else '',raw=card.text,images=image_urls(ancestor(card,'col-project__inner'),self.provenance(file)['original']),supplement=True)

    def extract(self):
        for method in [self.nominees_2012,self.winners_2012,self.shortlist_2013,self.winners_2013,self.winners_2015,self.shortlist_2014,self.past_winners,self.shortlist_2016,
                       lambda:self.shortlist_recent(2017),lambda:self.shortlist_recent(2017,'2017/shortlist-gen.html'),lambda:self.shortlist_recent(2018),lambda:self.shortlist_recent(2019),self.winners_2018,self.winners_2019,self.community,self.listings]:
            start=len(self.rows);method()
            self.stats.append({'parser':method.__name__,'nominations':len(self.rows)-start})
        return self.rows

    def identities(self, row):
        title=row['canonical']
        identities=[(row['year'],'url',url_key(u)) for u in row['links'][:1] if is_profile(u)]
        if title.endswith('...') or '\ufffd' in title:
            identities=[(row['year'],'url',url_key(u)) for u in row['links'][:1]]
        # WizeHive's shortened titles are not unique (two Mother Jones entries share one).
        if not title.endswith('...') and '\ufffd' not in title:
            identities.append((row['year'],'title',key(title)))
        return identities

    def build(self):
        self.extract()
        # Corrections are reviewed, source-specific facts; no fuzzy matching or inferred results.
        for row in self.rows+self.supplements:
            patch_key=f"{row['year']}|{row['title']}"
            if patch_key in self.patches.get('records',{}):
                row.update(self.patches['records'][patch_key]);self.used_patches.add(patch_key)
        aliases=self.patches.get('aliases',{})
        for row in self.rows+self.supplements:
            row['canonical']=aliases.get(f"{row['year']}|{row['title']}",row['title'])
        # A source record may be linked by URL, exact title, or a documented alias.
        groups=[]; indexes={}
        for row in self.rows:
            identities=self.identities(row)
            matches={indexes[i] for i in identities if i in indexes}
            if len(matches)>1:
                target=min(matches)
                for j in sorted(matches-{target}):
                    groups[target].extend(groups[j]);groups[j]=[]
                    for k,v in list(indexes.items()):
                        if v==j:indexes[k]=target
            elif matches:target=matches.pop()
            else:target=len(groups);groups.append([])
            groups[target].append(row)
            for identity in identities:indexes[identity]=target
        for row in self.supplements:
            identities=self.identities(row)
            match=next((indexes[i] for i in identities if i in indexes),None)
            if match is not None:
                supplemental=dict(row);supplemental['result']='';groups[match].append(supplemental)
        entries=[];details=defaultdict(dict)
        for rows in groups:
            if not rows:continue
            selected=[r for r in rows if r['result']]
            best=sorted(selected,key=lambda r:RANK[r['result']])[0]
            year=best['year']; title=best['canonical']
            stable_key=f'{year}|{key(title)}'
            if title.endswith('...') or '\ufffd' in title: stable_key += '|' + best['links'][0]
            entry_id=self.patches.get('ids',{}).get(stable_key,f'dja-{year}-{hashlib.sha256(stable_key.encode()).hexdigest()[:12]}')
            awards=[];sources=[];links=[];image_sources=[];image_references=[]
            for row in rows:
                if row['result'] and (row['category'] or not any(r['category'] for r in rows)):
                    canonical_cat=self.patches.get('categories',{}).get(f"{row['year']}|{row['category']}",row['category'])
                    award={'category':canonical_cat,'result':row['result'],'originalCategory':row['category'],'sourceFile':row['source']['file']}
                    if award not in awards:awards.append(award)
                if row['source'] not in sources:sources.append(row['source'])
                for link in row['links']:
                    if link not in links:links.append(link)
                for image in row['imageSources']:
                    if image and image not in image_sources:image_sources.append(image)
                    if image:
                        src=row['source']
                        snapshot=src['wayback'] or self.sources.get(src.get('groupFile',''),{}).get('wayback','')
                        ref={'url':image,'file':src['file'],'pageSnapshot':snapshot}
                        if ref not in image_references:image_references.append(ref)
            dedup={}
            for award in awards:
                cat_key=key(award['category'])
                evidence={'category':award['originalCategory'],'result':award['result'],'file':award['sourceFile']}
                if cat_key not in dedup:
                    dedup[cat_key]={'category':award['category'],'result':award['result'],'evidence':[]}
                current=dedup[cat_key]
                if RANK[award['result']]<RANK[current['result']]:current['result']=award['result']
                if evidence not in current['evidence']:current['evidence'].append(evidence)
            awards=list(dedup.values())
            kind=self.patches.get('kinds',{}).get(f'{year}|{title}',kind_for(best['category']))
            preferred=sorted(rows,key=lambda r:RANK.get(r['result'],3))
            org=next((r['org'] for r in preferred if r['org']),'')
            country=next((r['country'] for r in preferred if r['country']),'')
            country=COUNTRIES.get(country,country)
            summary=next((r['summary'] for r in rows if r['summary']),'')
            jury=next((r['jury'] for r in rows if r['jury']),'')
            summary_ja=self.patches.get('summariesJa',{}).get(f'{year}|{title}','')
            work_links=[u for u in links if not is_profile(u)]
            profile_links=[u for u in links if is_profile(u)]
            entry={'id':entry_id,'year':year,'title':title,'org':org,'country':country,'kind':kind,'result':best['result'],
                   'resultLabel':best['result'],'tags':[],'langs':'','summary':summary[:240], 'summaryJa':summary_ja,
                   'url':work_links[0] if work_links else '', 'awards':awards,'sources':sources}
            entries.append(entry)
            details[year][entry_id]={'summary':summary,'summaryJa':summary_ja,'jury':jury,'links':work_links,'profileLinks':profile_links,
                                    'imageSources':image_sources,'imageReferences':image_references,'awards':awards,'sources':sources,
                                    'sourceRecords':[{'file':r['source']['file'],'text':r['sourceText']} for r in rows if r['sourceText']]}
        entries.sort(key=lambda e:(-e['year'],RANK[e['result']],e['title'].casefold()))
        attach_thumbnails(entries,details)
        validate(entries,details)
        coverage=[]
        for year in range(2012,2020):
            yearly=[e for e in entries if e['year']==year]
            nominated=[r for r in self.rows if r['year']==year]
            coverage.append({'year':year,'count':len(yearly),'results':dict(Counter(e['result'] for e in yearly)),
                             'awardCount':sum(len(e['awards']) for e in yearly),'rawNominations':len(nominated),
                             'files':sorted({s['file'] for e in yearly for s in e['sources']}),
                             'notes':self.patches.get('coverageNotes',{}).get(str(year),[]),
                             'sourceChecks':[{'file':f,'extracted':sum(r['source']['file']==f and r['year']==year for r in self.rows),
                                              'supplementalRecords':sum(r['source']['file']==f and r['year']==year for r in self.supplements),
                                              'manifestCoverage':p.get('coverage','')} for f,p in self.sources.items()
                                             if str(p['year'])==str(year) or (isinstance(p['year'],str) and '-' in p['year'] and int(p['year'].split('-')[0])<=year<=int(p['year'].split('-')[1]))]})
        payload={'title':'Data Journalism Awards 受賞・候補一覧','source':'User-supplied DJA HTML archive','sourceSavedAt':self.manifest['saved_at'],
                 'count':len(entries),'years':list(range(2012,2020)),'coverage':coverage,'entries':entries}
        report={'htmlFiles':len(self.trees),'sourceFiles':[{'file':f,'sha256':hashlib.sha256((self.source/f).read_bytes()).hexdigest()} for f in self.trees],'parsers':self.stats,'coverage':coverage,
                'decodingWarnings':[f for f,t in self.trees.items() if '\ufffd' in t.text],
                'unusedCorrections':sorted(set(self.patches.get('records',{}))-self.used_patches)}
        return payload,details,report


def validate(entries,details):
    ids=set()
    for e in entries:
        if e['id'] in ids:raise ValueError(f"Duplicate ID: {e['id']}")
        ids.add(e['id'])
        if not e['title'] or not 2012<=e['year']<=2019 or not e['awards'] or not e['sources']:
            raise ValueError(f'Incomplete entry: {e}')
        if e['kind'] not in {'project','portfolio','individual','team','site'}:raise ValueError(f'Invalid kind: {e}')
        if any(a['result'] not in RANK for a in e['awards']):raise ValueError(f'Invalid result: {e}')
        if e['id'] not in details[e['year']]:raise ValueError(f"Missing details: {e['id']}")
        for u in [e['url']]+details[e['year']][e['id']]['links']+details[e['year']][e['id']]['profileLinks']:
            if u and not url_clean(u):raise ValueError(f'Invalid URL: {u}')
    if ids!={i for records in details.values() for i in records}:raise ValueError('Orphan details')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,default=DEFAULT_SOURCE,help='archive/ directory, or its parent')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'public/data/dja')
    args=parser.parse_args()
    source=args.source_dir
    if not (source/'manifest.json').exists():source=source/'archive'
    payload,details,report=Catalog(source).build()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    def write(name,obj):
        (args.output_dir/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    write('entries.json',payload)
    for year,records in details.items():write(f'details-{year}.json',records)
    write('build-report.json',report)
    print(f"DJA: {payload['count']} records / {report['htmlFiles']} HTML files")
    for y in payload['coverage']:print(y['year'],y['count'],y['results'],f"{y['awardCount']} award records")


if __name__=='__main__':main()
