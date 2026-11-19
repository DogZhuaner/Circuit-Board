(() => {
  const record = JSON.parse(document.getElementById('record').textContent);
  const {events, batches, initial_state: initial} = record;
  const el = id => document.getElementById(id);
  const board = el('board');
  const surface = el('surface');
  const layer = el('wire-layer');
  const contacts = new Map();
  const regions = buildRuleContactRegions();
  const pairKey = pair => JSON.stringify([...pair].sort());
  const columnOf = new Map();
  regions.forEach((region, i) => region.contacts.forEach(({name}) => columnOf.set(name, i)));
  const routes = new Map();
  const legacyNames = new Set();
  const pitch = 12;
  const laneCount = Array(regions.length + 1).fill(0);
  let topCount = 0;

  // Allocate once, in first-connection order. Removed wires keep their lanes.
  function planPair(pair) {
    const key = pairKey(pair);
    if (routes.has(key)) return;
    const [start, end] = pair;
    const a = columnOf.get(start), b = columnOf.get(end);
    if (a === undefined) legacyNames.add(start);
    if (b === undefined) legacyNames.add(end);
    const known = a !== undefined && b !== undefined;
    const startRight = known && a <= b;
    const endRight = known && b <= a;
    const firstGap = (a ?? 0) + Number(startRight);
    const lastGap = (b ?? 0) + Number(endRight);
    const firstLane = laneCount[firstGap]++;
    const route = {start, end, startRight, endRight, firstGap, lastGap, firstLane};
    if (firstGap !== lastGap) {
      route.lastLane = laneCount[lastGap]++;
      route.topLane = topCount++;
    }
    routes.set(key, route);
  }
  initial.pairs.forEach(planPair);
  events.forEach(event => planPair(event.terminals));
  const widths = laneCount.map((count, i) => count ? 8 + pitch * count
    : (i > 0 && i < regions.length ? 12 : 0));
  const roof = topCount ? 6 + topCount * pitch : 0;
  surface.style.minWidth = (704 + widths.reduce((sum, n) => sum + n, 0)) + 'px';
  surface.style.paddingTop = roof + 'px';
  surface.style.paddingRight = widths[regions.length] + 'px';
  Vue.createApp({
    setup() {
      return {
        ruleContactRegions: regions,
        ruleWirePlan: {gaps: widths.slice(0, regions.length), rowSpacing: {}},
        legacyNames: [...legacyNames],
        setRuleContactRef(name, node) {
          if (node) contacts.set(name, node);
          else contacts.delete(name);
        }
      };
    }
  }).mount('#catalog');
  const grid = surface.querySelector('.rule-canvas-scale');
  const edges = new Map();
  const scores = new Map(batches.filter(batch => batch.last_seq != null)
    .map(batch => [batch.last_seq, batch.score_after_batch]));
  let step = 0;
  let score = initial.score;
  let timer;
  el('seek').max = events.length;

  function updateGeometry() {
    const zoom = Number(el('zoom').value);
    surface.style.transform = `scale(${zoom})`;
    const origin = surface.getBoundingClientRect();
    const columns = [...grid.children].map(node => node.getBoundingClientRect());
    const left = columns.map((box, i) => (box.left - origin.left) / zoom - widths[i]);
    left.push((columns[columns.length - 1].right - origin.left) / zoom);
    function socket(name, right) {
      const button = contacts.get(name);
      const box = (right ? button.lastElementChild : button.firstElementChild).getBoundingClientRect();
      return {x: (box.left + box.width / 2 - origin.left) / zoom,
              y: (box.top + box.height / 2 - origin.top) / zoom};
    }
    for (const r of routes.values()) {
      const a = socket(r.start, r.startRight), b = socket(r.end, r.endRight);
      const x = left[r.firstGap] + 6 + r.firstLane * pitch;
      let path = `M ${a.x} ${a.y} H ${x}`;
      if (r.firstGap !== r.lastGap) {
        const endX = left[r.lastGap] + 6 + r.lastLane * pitch;
        path += ` V ${6 + r.topLane * pitch} H ${endX}`;
      }
      r.path = path + ` V ${b.y} H ${b.x}`;
    }
    surface.parentElement.style.width = Math.ceil(surface.offsetWidth * zoom) + 'px';
    surface.parentElement.style.height = Math.ceil(surface.offsetHeight * zoom) + 'px';
  }

  function drawWires() {
    const event = events[step - 1];
    const paths = document.createDocumentFragment();
    function wire(pair, color, dashed) {
      const key = pairKey(pair);
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', routes.get(key).path);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', color);
      path.setAttribute('stroke-width', dashed || (event && key === pairKey(event.terminals)) ? 3 : 1.8);
      if (event && key === pairKey(event.terminals)) path.classList.add('current-wire');
      if (dashed) path.setAttribute('stroke-dasharray', '6 5');
      paths.append(path);
    }
    for (const pair of edges.values()) wire(pair, '#27855f', false);
    if (event?.operation === 'remove') wire(event.terminals, '#af4e40', true);
    layer.replaceChildren(paths);
  }

  function revealEvent(event) {
    if (!event) return;
    const [a, b] = event.terminals.map(name => contacts.get(name).getBoundingClientRect());
    const view = board.getBoundingClientRect();
    const wire = layer.querySelector('.current-wire')?.getBoundingClientRect();
    const xBounds = wire && wire.width + 12 <= board.clientWidth
      ? [wire.left - 6, wire.right + 6] : [Math.min(a.left, b.left), Math.max(a.right, b.right)];
    const yBounds = wire && wire.height + 12 <= board.clientHeight
      ? [wire.top - 6, wire.bottom + 6] : [Math.min(a.top, b.top), Math.max(a.bottom, b.bottom)];
    function offset(lo, hi, first, start, size) {
      if (lo >= start && hi <= start + size) return 0;
      const center = hi - lo <= size ? (lo + hi) / 2 : first;
      return center - start - size / 2;
    }
    board.scrollBy(offset(...xBounds,
                          a.left + a.width / 2, view.left, board.clientWidth),
                   offset(...yBounds,
                          a.top + a.height / 2, view.top, board.clientHeight));
  }
  function draw() {
    const event = events[step - 1];
    for (const [name, button] of contacts) {
      button.classList.toggle('selected', Boolean(event?.terminals.includes(name)));
    }
    drawWires();
    revealEvent(event);
    const action = event ? (event.operation === 'add' ? '新增' : '撤回') + '　' + event.terminals.join(' ↔ ') : '初始接线';
    el('description').textContent = '第 ' + step + ' / ' + events.length + ' 步　' + action;
    el('score').textContent = '当前连接 ' + edges.size + ' 对　采集评分 ' +
      (step === events.length ? record.latest_state.score : score) +
      (event ? '　采集时间 +' + (event.elapsed_ms / 1000).toFixed(1) + ' 秒' : '');
    el('seek').value = step;
    el('prev').disabled = step === 0;
    el('next').disabled = step === events.length;
  }

  function seek(target) {
    if (target <= step) {
      step = 0;
      score = initial.score;
      edges.clear();
      initial.pairs.forEach(pair => edges.set(pairKey(pair), pair));
    }
    while (step < target) {
      const e = events[step++];
      if (e.operation === 'add') edges.set(pairKey(e.terminals), e.terminals);
      else edges.delete(pairKey(e.terminals));
      if (scores.has(e.seq)) score = scores.get(e.seq);
    }
    draw();
  }
  function pause() {
    clearTimeout(timer);
    timer = null;
    el('play').textContent = step === events.length && step ? '重新播放' : '播放';
  }
  function play() {
    if (step === events.length) seek(0);
    el('play').textContent = '暂停';
    function tick() {
      seek(step + 1);
      if (step === events.length) pause();
      else timer = setTimeout(tick, 1000 / Number(el('speed').value));
    }
    timer = setTimeout(tick, 1000 / Number(el('speed').value));
  }
  el('play').onclick = () => timer ? pause() : play();
  el('prev').onclick = () => { seek(step - 1); pause(); };
  el('next').onclick = () => { seek(step + 1); pause(); };
  el('seek').oninput = e => { seek(Number(e.target.value)); pause(); };
  function refreshLayout() {
    updateGeometry();
    drawWires();
  }
  el('zoom').onchange = () => { updateGeometry(); draw(); };
  if (window.ResizeObserver) new ResizeObserver(refreshLayout).observe(el('catalog'));
  else window.addEventListener('resize', refreshLayout);
  updateGeometry();
  seek(0);
  el('play').disabled = !events.length;
  if (events.length) play();
})();
