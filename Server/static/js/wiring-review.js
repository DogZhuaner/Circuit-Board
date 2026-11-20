(() => {
  const record = JSON.parse(document.getElementById('record').textContent);
  const {events, batches, initial_state: initial} = record;
  const el = id => document.getElementById(id);
  const contacts = new Map();
  const regions = buildRuleContactRegions();
  const pairKey = pair => JSON.stringify(pair.map(name => String(name).trim()).sort());
  const rules = JSON.parse(el('review-rules').textContent);
  const answers = new Map();
  const ruleTargets = new Map();
  const ruleStarts = new Set();
  for (const rule of rules || []) {
    const key = pairKey(rule.nodes);
    ruleStarts.add(rule.nodes[0].trim());
    if (!answers.has(key) || Number(rule.score) > Number(answers.get(key))) {
      answers.set(key, rule.score);
      ruleTargets.set(key, rule.nodes[1].trim());
    }
  }
  const knownNames = new Set(regions.flatMap(region => region.contacts.map(contact => contact.name)));
  const extraNames = new Set();
  const wires = new Map();
  function register(pair) {
    const id = pairKey(pair);
    if (wires.has(id)) return;
    for (const name of pair) if (!knownNames.has(name)) extraNames.add(name);
    wires.set(id, {id, start: pair[0], end: pair[1], score: answers.get(id)});
  }
  initial.pairs.forEach(register);
  events.forEach(event => register(event.terminals));
  if (extraNames.size) {
    regions.push({name: 'legacy', title: '记录中的其他端子', rowCount: extraNames.size + 1,
      contacts: [...extraNames].map((name, i) => ({name, row: i + 2}))});
  }

  // Plan all recorded edges once so seeking and undoing use the same physical tracks.
  const plan = planRuleWireTracks(regions, [...wires.values()]);
  // Historical wires can reuse a socket at different steps. Keep their leads centered.
  for (const route of plan.routes) {
    route.startOffset = 0;
    route.endOffset = 0;
  }
  const visibleWires = Vue.shallowRef([]);
  const edges = Vue.shallowReactive(new Map());
  const ruleScoreText = Vue.computed(() => {
    if (rules === null) return '暂无规则分值';
    let earned = 0, maximum = 0;
    for (const [key, score] of answers) {
      const points = score == null ? NaN : Number(score);
      maximum += points;
      if (edges.has(key)) earned += points;
    }
    const format = value => Number.isFinite(value) ? value.toLocaleString('zh-CN') : '—';
    return format(earned) + ' / ' + format(maximum) + ' 分';
  });
  Vue.createApp({
    setup() {
      const previewRules = (rules || []).map(({nodes, score}, index) => ({
        id: index + 1, pair: pairKey(nodes), start: nodes[0], end: nodes[1], score
      }));
      const ruleBuilder = Vue.computed(() => ({
        wires: previewRules.filter(wire => edges.has(wire.pair))
      }));
      Vue.watch(ruleBuilder, (current, previous) => {
        const index = current.wires.findLastIndex(wire => !previous.wires.includes(wire));
        if (index < 0) return;
        const panel = el('review-layout').querySelector('.rule-summary');
        const card = panel.querySelectorAll('.rule-preview-item')[index];
        const bounds = card.getBoundingClientRect();
        const top = panel.getBoundingClientRect().top + panel.clientTop;
        const bottom = top + panel.clientHeight;
        if (bounds.bottom > bottom) panel.scrollTop += Math.ceil(bounds.bottom - bottom);
        else if (bounds.top < top) panel.scrollTop -= Math.ceil(top - bounds.top);
      }, {flush: 'post'});
      return {
        ruleContactRegions: regions, ruleWirePlan: plan, visibleWires, wireColor, ruleBuilder, ruleScoreText,
        setRuleContactRef(name, node) {
          if (node) contacts.set(name, node);
          else contacts.delete(name);
        }
      };
    }
  }).mount('#review-layout');
  const board = el('board'), surface = el('surface');
  const grid = surface.querySelector('.rule-canvas-scale');
  surface.style.minWidth = (176 * regions.length + plan.gaps.reduce((sum, n) => sum + n, 0)) + 'px';
  let routes;
  const scores = new Map(batches.filter(batch => batch.last_seq != null)
    .map(batch => [batch.last_seq, batch.score_after_batch]));
  let step = 0;
  let score = initial.score;
  let timer;
  el('seek').max = events.length;

  function updateGeometry() {
    const zoom = Number(el('zoom').value);
    surface.style.transform = `scale(${zoom})`;
    const placed = getRuleWireRoutes(plan, surface, grid, name => contacts.get(name), zoom, surface.offsetWidth);
    routes = new Map(placed.map(wire => [wire.id, wire]));
    surface.parentElement.style.width = Math.ceil(surface.offsetWidth * zoom) + 'px';
    surface.parentElement.style.height = Math.ceil(surface.offsetHeight * zoom) + 'px';
  }

  function drawWires() {
    const event = events[step - 1];
    const current = event && pairKey(event.terminals);
    const removed = event?.operation === 'remove' ? current : null;
    const ids = [...edges.keys()];
    if (removed) ids.push(removed);
    visibleWires.value = ids.map(id => ({
      ...routes.get(id), current: id === current, removed: id === removed,
      color: rules === null ? '#64748b' : answers.has(id) ? '#27855f' : '#c03932'
    }));
  }

  function orderedTerminals(pair) {
    const [a, b] = pair.map(name => name.trim());
    const target = ruleTargets.get(pairKey(pair));
    // The recorder sorts pairs. For a wrong connection, use the sole known rule start
    // when available; otherwise keep the recorded order.
    const reverse = target === a || (target === undefined && ruleStarts.has(b) && !ruleStarts.has(a));
    return reverse ? [pair[1], pair[0]] : pair;
  }

  function revealTarget(name) {
    const button = contacts.get(name);
    const label = document.createRange();
    label.selectNodeContents(button.firstElementChild.nextElementSibling);
    const target = label.getBoundingClientRect();
    const view = board.getBoundingClientRect();
    board.scrollBy(target.left + target.width / 2 - view.left - board.clientLeft - board.clientWidth / 2,
                   target.top + target.height / 2 - view.top - board.clientTop - board.clientHeight / 2);
  }
  function draw() {
    const event = events[step - 1];
    for (const [name, button] of contacts) {
      button.classList.toggle('selected', Boolean(event?.terminals.includes(name)));
    }
    drawWires();
    let action = '初始接线';
    if (event) {
      const pair = orderedTerminals(event.terminals);
      Vue.nextTick(() => { if (events[step - 1] === event) revealTarget(pair[1]); });
      const correct = rules === null ? null : answers.has(pairKey(event.terminals));
      const verdict = correct === null ? '无法判定' : correct ? '正确' : '错误';
      action = (event.operation === 'add' ? '新增' : '撤销') + '　' + pair.join(' → ') + '（' + verdict + '）';
    }
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
  if (window.ResizeObserver) new ResizeObserver(refreshLayout).observe(grid);
  else window.addEventListener('resize', refreshLayout);
  updateGeometry();
  seek(0);
  el('play').disabled = !events.length;
  if (events.length) play();
})();
