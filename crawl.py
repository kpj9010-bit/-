import json, re, sys
from datetime import datetime
from html.parser import HTMLParser
import urllib.request

# ─── HTML 테이블 파싱기 ───────────────────────────────
class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []          # 모든 테이블
        self.current_table = None
        self.current_row = None
        self.current_cell = None
        self.in_td = False

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.current_table = []
        elif tag == 'tr' and self.current_table is not None:
            self.current_row = []
        elif tag in ('td','th') and self.current_row is not None:
            self.current_cell = ''
            self.in_td = True

    def handle_endtag(self, tag):
        if tag == 'table' and self.current_table is not None:
            self.tables.append(self.current_table)
            self.current_table = None
        elif tag == 'tr' and self.current_row is not None and self.current_table is not None:
            self.current_table.append(self.current_row)
            self.current_row = None
        elif tag in ('td','th') and self.in_td:
            self.current_row.append(self.current_cell.strip() if self.current_cell else '')
            self.in_td = False
            self.current_cell = None

    def handle_data(self, data):
        if self.in_td and self.current_cell is not None:
            self.current_cell += data

def parse_tables(html):
    p = TableParser()
    p.feed(html)
    return p.tables

def fetch(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    with urllib.request.urlopen(req, timeout=15) as res:
        return res.read().decode('utf-8', errors='replace')

def clean(s):
    """공백·줄바꿈 정리"""
    return re.sub(r'\s+', ' ', s).strip() if s else ''

def parse_datetime(s):
    """날짜문자열 → MM.DD HH:MM 형태로 정규화"""
    s = clean(s)
    if not s or s == '미정': return s
    # 2026-02-02 11:00  또는  2026-02-0211:00
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})\s*([\d:]+)', s)
    if m:
        time_part = m.group(4)
        if ':' not in time_part and len(time_part) == 4:
            time_part = time_part[:2] + ':' + time_part[2:]
        return f"{m.group(2)}.{m.group(3)} {time_part}"
    # 02월03일 06시30분
    m = re.match(r'(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2})시\s*(\d{1,2})분', s)
    if m:
        return f"{m.group(1).zfill(2)}.{m.group(2).zfill(2)} {m.group(3).zfill(2)}:{m.group(4).zfill(2)}"
    return s

# ─── 각 사이트 크롤링 ─────────────────────────────────

def crawl_hyo():
    """강원효장례문화원 — e-baro.co.kr"""
    ALL = ['101호','201호','202호','301호','302호']
    html = fetch('https://e-baro.co.kr/api_view/?code=icBnKH')
    tables = parse_tables(html)
    occupied = {}
    for table in tables:
        for row in table:
            # 헤더행 건너뛰기
            if len(row) >= 7 and row[1] and row[2] and '번호' not in row[0]:
                num = clean(row[1])
                name = clean(row[2])
                if num and name:
                    occupied[num] = {
                        'num': num, 'name': name, 'occ': True,
                        'place': clean(row[4]),
                        'checkin': parse_datetime(row[5]),
                        'checkout': parse_datetime(row[6])
                    }
    return [occupied.get(n, {'num': n, 'occ': False}) for n in ALL]

def crawl_hoban():
    """호반병원장례식장 — hobanfuneral.co.kr"""
    ALL = ['1호(특실)','2호','3호','5호','6호','7호','8호']
    html = fetch('http://www.hobanfuneral.co.kr/index.php?mid=sub43&sort_index=var1&order_type=asc')
    tables = parse_tables(html)
    occupied = {}
    for table in tables:
        for row in table:
            # 헤더: [빈소명, 고인명, 입관일시, 상주, 장지, 발인일시, 비고]
            if len(row) >= 6 and row[0] and row[1] and '빈소명' not in row[0]:
                num = clean(row[0])
                name = clean(row[1])
                if num and name and any(num.startswith(n.replace('(특실)','')) for n in ALL):
                    # 1호 → 1호(특실) 매핑
                    matched = num
                    if num == '1호':
                        matched = '1호(특실)'
                    occupied[matched] = {
                        'num': matched, 'name': name, 'occ': True,
                        'place': clean(row[4]),
                        'checkin': parse_datetime(row[2]),
                        'checkout': parse_datetime(row[5])
                    }
    return [occupied.get(n, {'num': n, 'occ': False}) for n in ALL]

def crawl_gangwon():
    """강원대학교병원장례식장 — m.knuh.or.kr"""
    ALL = ['1호','2호','3호','5호','6호','7호']
    html = fetch('https://m.knuh.or.kr/hospitalinfor/funeral_01.asp')
    tables = parse_tables(html)
    occupied = {}
    for table in tables:
        # 빈소 테이블 패턴: R0 = [빈 소 명, 호실, 고인명]
        if len(table) >= 5:
            r0 = table[0]
            if len(r0) >= 3 and '소' in r0[0] and '명' in r0[0]:
                raw_room = clean(r0[1])  # "2호실(1층)"
                name = clean(r0[2])      # "지 춘 만(성도)"
                # 호실 번호 추출: "2호실(1층)" → "2호"
                m = re.match(r'(\d+)호', raw_room)
                if not m: continue
                num = m.group(1) + '호'
                # 고인명에서 괄호 안 내용 제거: "지 춘 만(성도)" → "지춘만"
                name = re.sub(r'\(.*?\)', '', name).replace(' ', '')
                # 장지, 입관, 발인 파싱
                place = checkin = checkout = ''
                for row in table[1:]:
                    if len(row) >= 2:
                        label = clean(row[0])
                        val = clean(row[1])
                        if '장' in label and '지' in label: place = val
                        elif '입관' in label: checkin = parse_datetime(val)
                        elif '발인' in label: checkout = parse_datetime(val)
                occupied[num] = {
                    'num': num, 'name': name, 'occ': True,
                    'place': place, 'checkin': checkin, 'checkout': checkout
                }
    return [occupied.get(n, {'num': n, 'occ': False}) for n in ALL]

def crawl_chuncheon():
    """춘천장례식장 — e-iris.co.kr"""
    ALL = ['101호','102호','201호','202호','301호']
    html = fetch('https://e-iris.co.kr/display/parlor/iframe/324')
    tables = parse_tables(html)
    occupied = {}
    for table in tables:
        for row in table:
            # 헤더: [번호, 빈소, 고인, 상주, 장지, 입관, 발인]
            if len(row) >= 7 and row[1] and row[2] and '번호' not in row[0]:
                raw_num = clean(row[1])  # "[무빈소] 무빈소2" 형태 가능
                name = clean(row[2]).replace('故','')
                # 빈소명에서 호수 추출
                m = re.search(r'(\d+호)', raw_num)
                if not m: continue
                num = m.group(1)
                occupied[num] = {
                    'num': num, 'name': name, 'occ': True,
                    'place': clean(row[4]),
                    'checkin': parse_datetime(row[5]),
                    'checkout': parse_datetime(row[6])
                }
    return [occupied.get(n, {'num': n, 'occ': False}) for n in ALL]

# ─── 메인 ─────────────────────────────────────────────
def main():
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    data = { 'updated': now, 'parlors': [] }

    crawlers = [
        ('chuncheon', '춘천장례식장', '033-256-4444', 'tel:03325644444',
         'https://e-iris.co.kr/display/parlor/iframe/324', crawl_chuncheon),
        ('hyojanglye', '강원효장례문화원', '033-261-4441', 'tel:03326144441',
         'https://e-baro.co.kr/api_view/?code=icBnKH', crawl_hyo),
        ('hoban', '호반병원장례식장', '033-252-0046', 'tel:03325200046',
         'http://www.hobanfuneral.co.kr/index.php?mid=sub43&sort_index=var1&order_type=asc', crawl_hoban),
        ('gangwon-univ', '강원대학교병원장례식장', '033-254-5611', 'tel:03325445611',
         'https://m.knuh.or.kr/hospitalinfor/funeral_01.asp', crawl_gangwon),
    ]

    for pid, name, tel, telHref, origUrl, crawler in crawlers:
        try:
            binsos = crawler()
            data['parlors'].append({
                'id': pid, 'name': name, 'tel': tel, 'telHref': telHref,
                'origUrl': origUrl, 'binsos': binsos
            })
            occ = sum(1 for b in binsos if b.get('occ'))
            print(f"✅ {name}: 사용중 {occ}/{len(binsos)}")
        except Exception as e:
            print(f"❌ {name}: {e}", file=sys.stderr)
            data['parlors'].append({
                'id': pid, 'name': name, 'tel': tel, 'telHref': telHref,
                'origUrl': origUrl, 'binsos': [], 'error': str(e)
            })

    # 시민장례식장 (수동)
    data['parlors'].append({
        'id': 'citizen', 'name': '춘천 시민장례식장',
        'tel': None, 'telHref': None, 'origUrl': None,
        'updating': True, 'binsos': []
    })

    print(json.dumps(data, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
