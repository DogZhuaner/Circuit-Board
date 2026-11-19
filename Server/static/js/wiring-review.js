(() => {
  const record = JSON.parse(document.getElementById('record').textContent);
  const {events, batches, initial_state: initial} = record;
  const el = id => document.getElementById(id);
  const canvas = el('board');
  const ctx = canvas.getContext('2d');
  const pairKey = pair => JSON.stringify([...pair].sort());
  const names = new Set(initial.pairs.flat());
  for (const event of events) event.terminals.forEach(name => names.add(name));
  const terminals = [...names].sort();
  const edges = new Map();
  const scores = new Map(batches.filter(batch => batch.last_seq != null)
    .map(batch => [batch.last_seq, batch.score_after_batch]));
  let step = 0;
  let score = initial.score;
  let timer;
  el('seek').max = events.length;

  function draw() {
    const width = canvas.clientWidth;
    const columns = Math.max(2, Math.min(6, Math.floor(width / 145)));
    const height = Math.max(220, 82 * Math.ceil(terminals.length / columns) + 48);
    const scale = window.devicePixelRatio || 1;
    canvas.style.height = height + 'px';
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    ctx.scale(scale, scale);
    const points = new Map(terminals.map((name, i) => [name, [
      width * ((i % columns) + 0.5) / columns, 38 + Math.floor(i / columns) * 82
    ]]));
    const event = events[step - 1];
    function wire(pair, color, dashed) {
      const [x, y] = points.get(pair[0]);
      const [u, v] = points.get(pair[1]);
      ctx.strokeStyle = color;
      ctx.lineWidth = dashed || (event && pairKey(pair) === pairKey(event.terminals)) ? 3 : 1.8;
      ctx.setLineDash(dashed ? [6, 5] : []);
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.quadraticCurveTo((x + u) / 2 + (x === u ? 30 : 0), (y + v) / 2 - 28, u, v);
      ctx.stroke();
    }
    for (const pair of edges.values()) wire(pair, '#27855f', false);
    if (event?.operation === 'remove') wire(event.terminals, '#af4e40', true);
    ctx.setLineDash([]);
    ctx.font = '14px system-ui';
    ctx.textAlign = 'center';
    for (const [name, [x, y]] of points) {
      ctx.fillStyle = event?.terminals.includes(name) ? '#1d7651' : '#597168';
      ctx.beginPath(); ctx.arc(x, y, 6, 0, 2 * Math.PI); ctx.fill();
      ctx.fillStyle = '#1f382f';
      ctx.fillText(name, x, y + 23, width / columns - 8);
    }
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
  window.addEventListener('resize', draw);
  seek(0);
  el('play').disabled = !events.length;
  if (events.length) play();
})();
