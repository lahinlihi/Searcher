// 모든 화면이 함께 쓰는 출력 안전 함수. base.html 의 <head> 에서 가장 먼저 불러온다.
//
// 공고 제목·기관명·첨부 파일명·오류 문구는 우리가 쓴 글이 아니라 외부 사이트와
// API 에서 받아 온 글자다. 이것을 innerHTML 에 그대로 끼워 넣으면 그 안의
// <태그> 가 화면을 보고 있는 사람의 브라우저에서 실행된다.
// 화면에 넣기 전에 반드시 아래 함수 중 하나를 거친다.

// HTML 본문·속성값에 넣을 글자. 따옴표까지 바꾸므로 속성값 안에서도 안전하다.
function safeHtml(value) {
    return String(value ?? '').replace(/[&<>"'`]/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;',
        '"': '&quot;', "'": '&#39;', '`': '&#96;',
    }[c]));
}

// href 에 넣을 주소. http(s) 와 사이트 내부 경로만 통과시킨다.
// (javascript: 주소는 클릭하는 순간 스크립트로 실행된다)
function safeUrl(value) {
    const u = String(value ?? '').trim();
    if (/^https?:\/\//i.test(u) || (u.startsWith('/') && !u.startsWith('//'))) {
        return safeHtml(u);
    }
    return '#';
}

// 정규식에 넣을 글자. 'C++', '(주' 같은 검색어가 정규식 문법으로 읽히지 않게 한다.
function escapeRegExp(value) {
    return String(value ?? '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// 글자 안의 키워드를 <mark> 로 감싼 HTML 을 돌려준다.
// 원문을 조각내 조각마다 이스케이프하므로 결과에는 우리가 넣은 <mark> 만 태그로 남는다.
// 키워드를 하나씩 차례로 바꾸지 않고 한 번에 찾는다 — 차례로 바꾸면 앞서 넣은
// <mark class="..."> 안의 글자('mark', 'class')가 다음 키워드에 다시 걸린다.
function highlightSafe(text, keywords, markClass) {
    const s = String(text ?? '');
    const ks = (keywords || []).filter(Boolean).map(String)
        .sort((a, b) => b.length - a.length);
    if (!ks.length) return safeHtml(s);
    const re = new RegExp(ks.map(escapeRegExp).join('|'), 'gi');
    const cls = safeHtml(markClass || 'keyword-highlight');
    let out = '';
    let last = 0;
    let m;
    while ((m = re.exec(s)) !== null) {
        if (m[0] === '') { re.lastIndex++; continue; }
        out += safeHtml(s.slice(last, m.index))
            + `<mark class="${cls}">` + safeHtml(m[0]) + '</mark>';
        last = m.index + m[0].length;
    }
    return out + safeHtml(s.slice(last));
}
