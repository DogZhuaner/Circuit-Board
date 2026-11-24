(() => {
  const el = id => document.getElementById("vp-" + id);
  const dialog = document.getElementById("vp");
  const board = el("board");
  const colors = ["#097268","#b9562e","#356fa4","#845798","#80712a","#386354"];
  const ink = "#293454";
  let equivalent;
  let doc, panel, file, epoch = 0;
  const pinName=ref=>ref.startsWith("INV:") ? ref.slice(4) : ref.replace(":","-");
  let wireShapes=[], pinShapes=new Map();
  function selectWire(index){
    const wire=panel.wires[index];
    const evidence=panel.evidence?.find(e=>e.pins.includes(wire.from) && e.pins.includes(wire.to));
    el("boxes").replaceChildren();
    if(evidence?.source === "schematic") {
      el("basis").textContent=evidence.basis;
      for(const [x,y,right,bottom] of evidence.boxes){
        const box=document.createElement("span");
        Object.assign(box.style,{left:x/10+"%",top:y/10+"%",width:(right-x)/10+"%",height:(bottom-y)/10+"%"});
        el("boxes").append(box);
      }
    } else {
      el("basis").textContent=evidence?.basis || "此连线无原图位置记录";
    }
    wireShapes.forEach((shape,i)=>{
      shape.classList.toggle("vp-selected-wire",i===index);
      shape.classList.toggle("vp-muted-wire",i!==index);
    });
    wireShapes[index].parentNode.append(wireShapes[index]);
    pinShapes.forEach((shape,ref)=>{
      const selected=ref===wire.from || ref===wire.to;
      shape.classList.toggle("vp-selected-pin",selected);
      if(selected)shape.parentNode.append(shape);
    });
    el("wires").querySelectorAll("button").forEach((button,i)=>button.setAttribute("aria-pressed",String(i===index)));
  }
  function ruleWires(){
    return panel.wires.map((wire,index)=>({id:index+1,groupId:index+1,start:pinName(wire.from),end:pinName(wire.to),score:1}));
  }
  el("save").onclick = () => {
    const rows = teacherUI.buildExportedRules(ruleWires());
    const url = URL.createObjectURL(new Blob([JSON.stringify(rows, null, 2)], {type: "application/json"}));
    const link = document.createElement("a");
    link.href = url;
    link.download = doc.title.replace(/\.json$/i, "") + ".json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  function openRules(importAI){
    const state=teacherUI.ruleBuilder;
    if(importAI){
      if(state.wires.length && !confirm("用当前 AI 接线表替换规则编辑器中的连线？"))return;
      const wires=ruleWires();
      Object.assign(state,{filename:doc.title,wires,selectedContact:null,activeGroupId:null,
        nextWireId:wires.length+1,nextGroupId:wires.length+1});
    }
    teacherUI.ruleImage=el("source-link").getAttribute("href") || "";
    dialog.close();teacherUI.openRuleBuilderModal();
  }
  el("edit").onclick=()=>openRules(true);
  el("manual").onclick=()=>openRules(false);
  function wireLabel(wire) {
    return pinName(wire.from) + " ↔ " + pinName(wire.to);
  }
  function svg(tag, attrs, text) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs).forEach(([key,value]) => node.setAttribute(key,value));
    if (text !== undefined) node.textContent = text;
    board.appendChild(node);
    return node;
  }
  // Use the same terminal inventory and ordering as the manual rule editor.
  function draw(result) {
    board.replaceChildren();wireShapes=[];pinShapes.clear();
    const rows = RULE_CONTACT_REGIONS.map(row => ({title:row.title, keys:row.contacts, parts:new Map()}));
    for (const part of doc.components) for (const pin of part.pins) {
      const key = pinName(part.id + ":" + pin);
      const row = rows.find(r => r.keys.includes(key));
      if (!row) continue;
      if (!row.parts.has(part.id)) row.parts.set(part.id,[]);
      row.parts.get(part.id).push({pin,key,ref:part.id+":"+pin,label:part.label});
    }
    const positions = new Map(), groups = [];
    let maxX = 650, y = 32;
    for (const row of rows.filter(r=>r.parts.size)) {
      let x = 26;
      const parts = [...row.parts].sort((a,b)=>row.keys.indexOf(a[1][0].key)-row.keys.indexOf(b[1][0].key));
      groups.push({name:row.title,y});
      for (const [id,pins] of parts) {
        pins.sort((a,b)=>row.keys.indexOf(a.key)-row.keys.indexOf(b.key));
        const pitch = Math.max(44,...pins.map(p=>p.pin.length*9+14));
        const width = Math.max(108,pins.length*pitch+20,id.length*10+22);
        groups.push({id,label:pins[0].label,x,y:y+17,width});
        pins.forEach((p,i)=>positions.set(p.ref,{x:x+width/2+pitch*(i-(pins.length-1)/2),y:y+89,pin:p.pin}));
        x += width+15;
      }
      maxX=Math.max(maxX,x+10);
      const touched = result.wires.filter(w=>[w.from,w.to].some(key=>positions.get(key)?.y===y+89)).length;
      y+=122+touched*10;
    }
    const track = new Map();
    function channel(p){const used=track.get(p.y)||0;track.set(p.y,used+1);return p.y+15+used*10;}
    let side=0;
    groups.forEach(g=>{
      if (!g.id) {svg("text",{x:26,y:g.y,fill:"#527169","font-size":13},g.name);return}
      const rect=svg("rect",{x:g.x,y:g.y,width:g.width,height:72,rx:5,fill:"#fff",stroke:"#aab6d0"});
      const title=document.createElementNS(board.namespaceURI,"title");title.textContent=g.label;rect.append(title);
      svg("rect",{x:g.x+1,y:g.y+1,width:g.width-2,height:24,rx:4,fill:"#e2e6fa"});
      svg("text",{x:g.x+10,y:g.y+17,fill:ink,"font-size":14,"font-weight":700},g.id);
      const available = Math.max(4,Math.floor((g.width-20)/12));
      const caption = g.label.length > available ? g.label.slice(0,available-1)+"…" : g.label;
      svg("text",{x:g.x+10,y:g.y+43,fill:"#526486","font-size":11},caption);
    });
    for(const wire of result.wires){
      const a=positions.get(wire.from),b=positions.get(wire.to), first=channel(a);
      let d="M "+a.x+" "+a.y+" V "+first;
      if(a.y!==b.y){const end=channel(b), lane=maxX+10*(++side);d+=" H "+lane+" V "+end;}
      d+=" H "+b.x+" V "+b.y;
      const color=colors[(Number(wire.net.slice(1))-1)%colors.length];
      svg("path",{d,fill:"none",stroke:"#f0f5ef","stroke-width":5,"stroke-linejoin":"round"});
      const line=svg("path",{d,fill:"none",stroke:color,"stroke-width":2.5,"stroke-linejoin":"round"});
      const title=document.createElementNS(board.namespaceURI,"title");title.textContent=wire.net+" · "+wireLabel(wire);line.append(title);wireShapes.push(line);
    }
    positions.forEach((p,ref)=>{
      svg("text",{x:p.x,y:p.y-13,"text-anchor":"middle","font-size":12,fill:ink},p.pin);
      pinShapes.set(ref,svg("circle",{cx:p.x,cy:p.y,r:4,fill:"#fff",stroke:ink,"stroke-width":2}));
    });
    const width=maxX+side*10+18;
    board.setAttribute("viewBox","0 0 "+width+" "+y);
    el("zoom").hidden=false;
    scene={width,height:y};
    fit();
  }

  const viewport=el("scroll");
  let scene=null, zoom=1, cx=0, cy=0, drag=null;
  function scale(){
    return Math.min(viewport.clientWidth/scene.width,viewport.clientHeight/scene.height)*zoom;
  }
  function paint(){
    if(!scene || !viewport.clientWidth || !viewport.clientHeight)return;
    const w=viewport.clientWidth/scale(), h=viewport.clientHeight/scale();
    const clamp=(c,size,span)=>span>=size?size/2:Math.max(span/2,Math.min(size-span/2,c));
    cx=clamp(cx,scene.width,w);cy=clamp(cy,scene.height,h);
    board.setAttribute("viewBox",[cx-w/2,cy-h/2,w,h].join(" "));
    el("percent").value=Math.round(zoom*100)+"%";
    el("out").disabled=zoom<=1;el("in").disabled=zoom>=16;
  }
  function fit(){
    if(!scene)return;
    zoom=1;cx=scene.width/2;cy=scene.height/2;paint();
  }
  function magnify(factor,x=0,y=0){
    if(!scene)return;
    const old=scale();
    zoom=Math.min(16,Math.max(1,zoom*factor));
    cx+=x*(1/old-1/scale()); cy+=y*(1/old-1/scale());paint();
  }
  function atPointer(e,factor){
    const box=board.getBoundingClientRect();
    magnify(factor,e.clientX-box.left-box.width/2,e.clientY-box.top-box.height/2);
  }
  viewport.addEventListener("wheel",e=>{
    if(!scene)return;
    e.preventDefault();atPointer(e,Math.exp(-Math.max(-150,Math.min(150,e.deltaY))*0.003));
  },{passive:false});
  viewport.ondblclick=e=>atPointer(e,2);
  viewport.onpointerdown=e=>{
    if(!scene || e.button!==0)return;
    drag={id:e.pointerId,x:e.clientX,y:e.clientY};viewport.setPointerCapture(e.pointerId);
  };
  viewport.onpointermove=e=>{
    if(!drag || drag.id!==e.pointerId)return;
    cx+=(drag.x-e.clientX)/scale();cy+=(drag.y-e.clientY)/scale();
    drag.x=e.clientX;drag.y=e.clientY;paint();
  };
  viewport.onlostpointercapture=()=>{drag=null};
  el("in").onclick=()=>magnify(1.5);el("out").onclick=()=>magnify(1/1.5);
  el("fit").onclick=fit;
  new ResizeObserver(paint).observe(viewport);
  const dock=el("dock");
  const clampSize=(value,min,max)=>Math.min(max,Math.max(min,value));
  function sizeToEdges(edge,box,dx,dy){
    const vw=document.documentElement.clientWidth, vh=window.innerHeight;
    const minW=Math.min(300,vw), minH=Math.min(250,vh);
    let {left,right,top,bottom}=box;
    if(edge.includes("w"))left=clampSize(left+dx,0,right-minW);
    if(edge.includes("e"))right=clampSize(right+dx,left+minW,vw);
    if(edge.includes("n"))top=clampSize(top+dy,0,bottom-minH);
    if(edge.includes("s"))bottom=clampSize(bottom+dy,top+minH,vh);
    dialog.style.setProperty("--vp-x",left+"px");
    dialog.style.setProperty("--vp-y",top+"px");
    dialog.style.setProperty("--vp-w",(right-left)+"px");
    dialog.style.setProperty("--vp-h",(bottom-top)+"px");
    dialog.classList.add("vp-sized");
  }
  for(const edge of ["n","e","s","w","ne","se","sw","nw"]){
    const handle=document.createElement("span");
    handle.className="vp-edge";handle.dataset.edge=edge;
    handle.setAttribute("aria-hidden","true");
    dialog.append(handle);
    let start=null;
    handle.onpointerdown=e=>{
      if(!e.isPrimary || e.button!==0)return;
      e.preventDefault();
      start={id:e.pointerId,x:e.clientX,y:e.clientY,box:dialog.getBoundingClientRect()};
      handle.setPointerCapture(e.pointerId);
      dialog.classList.add("vp-sizing");
    };
    handle.onpointermove=e=>{
      if(start && start.id===e.pointerId)sizeToEdges(edge,start.box,e.clientX-start.x,e.clientY-start.y);
    };
    handle.onlostpointercapture=()=>{start=null;dialog.classList.remove("vp-sizing");};
  }
  function openCard(){
    dock.hidden=true;
    if(!dialog.open)dialog.show();
    requestAnimationFrame(paint);
  }
  el("min").onclick=()=>{dialog.close();dock.hidden=false;dock.focus();};
  dock.onclick=openCard;
  el("max").onclick=()=>{
    const maximized=dialog.classList.toggle("vp-maximized");
    const button=el("max");
    button.textContent=maximized?"❐":"□";
    button.title=maximized?"还原大小":"最大化";button.setAttribute("aria-label",button.title);
  };
  function clear(){
    equivalent=null;el("plan").checked=false;el("plan-option").hidden=true;
    el("networks").hidden=true;el("network-list").replaceChildren();
    pages=[];el("pager").hidden=true;
    el("zoom").hidden=true;
    scene=null;doc=null;panel=null;board.replaceChildren();el("controls").hidden=true;el("empty").hidden=false;

  }
  let pages=[], pageIndex=0;
  function displayPage(index){
    if(index<0 || index>=pages.length)return;
    pageIndex=index;
    show(pages[index]);
    el("wires").scrollTop=0;
    el("pager").hidden=pages.length<2;
    el("page").textContent="方案 "+(index+1)+" / "+pages.length+" · "+doc.title;
    el("prev").disabled=index===0;
    el("next").disabled=index===pages.length-1;
  }
  el("prev").onclick=()=>displayPage(pageIndex-1);
  el("next").onclick=()=>displayPage(pageIndex+1);
  function show(result){
    panel=result;doc=panel.netlist;draw(panel);
    el("save").disabled = !panel.wires.length;
    el("edit").disabled = !panel.wires.length;
    el("empty").hidden=true;el("controls").hidden=false;
    el("wires").replaceChildren(...panel.wires.map((w,i)=>{
      const li=document.createElement("li");
      const button=document.createElement("button");
      button.textContent=wireLabel(w);button.setAttribute("aria-pressed","false");
      button.onclick=()=>selectWire(i);li.append(button);
      return li;
    }));
    el("wire-title").textContent="接线对 · "+panel.wires.length;
    el("status").textContent=doc.uncertainties.join("；");
    if(panel.excluded_count)el("status").textContent+=" 已排除 "+panel.excluded_count+" 个盘外端子，仅导出盘内规则。";
  }
  async function post(url,options){
    const response=await fetch(url,{method:"POST",...options});
    const data=await response.json();
    if(!response.ok)throw Error(data.error||"请求失败");return data;
  }
  async function renderDiagram(netlist){
    const nonce=++epoch;
    try {
      const result=await post(dialog.dataset.diagram,{headers:{"Content-Type":"application/json"},body:JSON.stringify({netlist})});
      if(nonce===epoch)show(result);
    } catch(e){if(nonce===epoch)el("status").textContent=e.message;}
  }
  document.getElementById("vision-panel-open").onclick=openCard;
  el("plan").onchange=()=>show(el("plan").checked ? equivalent : pages[pageIndex]);
  el("close").onclick=()=>dialog.close();
  let sourceUrl;
  function setSource(url){
    if(sourceUrl?.startsWith("blob:")) URL.revokeObjectURL(sourceUrl);
    sourceUrl=url;
    el("boxes").replaceChildren();
    el("basis").textContent="";
    el("source-section").hidden=!url;
    if(url){
      el("source").src=url;
      el("source-link").href=url;
    } else {
      el("source").removeAttribute("src");
      el("source-link").removeAttribute("href");
    }
  }
  el("file").onchange=()=>{
    const selected=el("file").files[0];
    if(!selected)return;
    file=selected;
    setSource(URL.createObjectURL(file));
    analyze();
  };
  el("reset").onclick=()=>{
    ++epoch;clear();file=null;el("file").value="";
    setSource(null);el("run").disabled=true;el("status").textContent="请选择原理图。";
  };
  const settings = el("model-dialog");
  const provider = el("provider");
  const address = el("service-url");
  const keyInput = el("service-key");
  const modelInput = el("model-id");
  const modelStorage = "circuit.teacher.visionModel.v1";
  const serverModel = dialog.dataset.defaultModel;
  let config = {provider:"default", address:"", model:serverModel, key:""};
  try {
    const saved = JSON.parse(sessionStorage.getItem(modelStorage));
    if (saved && Array.from(provider.options).some(o => o.value === saved.provider)
        && typeof saved.model === "string" && saved.model && typeof saved.address === "string") {
      config = {provider:saved.provider, address:saved.address, model:saved.model, key:""};
    }
  } catch { /* Storage may be unavailable in private browsing. */ }
  function labelModel(){
    el("settings").textContent = "配置模型服务";
    el("settings").title = "当前模型：" + config.model;
  }
  function modelFields(selection){
    const form = new FormData();
    form.set("model", selection.model);
    if (selection.provider !== "default") {
      form.set("protocol", selection.provider);
      form.set("service_url", selection.address);
      if (selection.key) form.set("service_key", selection.key);
    }
    return form;
  }
  function draft(){
    return {provider:provider.value, address:address.value.trim(), model:modelInput.value.trim(), key:keyInput.value.trim()};
  }
  function connectionFields(){
    const custom = provider.value !== "default";
    el("connection").hidden = !custom;
    address.required = custom;
  }
  let listVersion = 0;
  function resetChoices(){
    listVersion++;
    el("model-choices").replaceChildren();
    el("model-status").textContent = "";
    el("list-models").disabled = false;
  }
  labelModel();
  el("settings").onclick = () => {
    provider.value=config.provider; address.value=config.address;
    modelInput.value=config.model; keyInput.value=config.key;
    connectionFields(); resetChoices(); settings.showModal();
  };
  provider.onchange = () => {
    resetChoices(); connectionFields(); keyInput.value="";
    address.value = ({anthropic:"https://api.anthropic.com/v1", gemini:"https://generativelanguage.googleapis.com/v1beta"})[provider.value] || "";
    modelInput.value = provider.value === "default" ? serverModel : "";
  };
  address.oninput = () => {keyInput.value=""; resetChoices();};
  keyInput.oninput = resetChoices;
  el("list-models").onclick = async () => {
    if (!address.reportValidity()) return;
    const version = ++listVersion;
    el("model-status").textContent="正在读取模型列表…";
    el("list-models").disabled=true;
    try {
      const {models} = await post(dialog.dataset.models,{body:modelFields(draft())});
      if (version !== listVersion) return;
      el("model-choices").replaceChildren(...models.map(id => new Option(id,id)));
      el("model-status").textContent = models.length ? "已读取 " + models.length + " 个模型，请选择支持图像输入的模型。" : "列表为空，可手动输入模型 ID。";
      modelInput.focus();
    } catch(e) {
      if (version === listVersion) el("model-status").textContent=e.message+" 也可手动输入模型 ID。";
    } finally {
      if (version === listVersion) el("list-models").disabled=false;
    }
  };
  el("model-cancel").onclick = () => settings.close();
  settings.onclose = () => {resetChoices(); keyInput.value="";};
  el("model-form").onsubmit = event => {
    event.preventDefault();
    const next = draft();
    if (!next.model || (next.provider !== "default" && !next.address)) {
      el("model-status").textContent="请填写模型 ID 和所选服务的地址。"; return;
    }
    config = next;
    try {
      sessionStorage.setItem(modelStorage, JSON.stringify({provider:next.provider,address:next.address,model:next.model}));
    } catch { /* Keep the selection in memory. */ }
    labelModel(); settings.close();
    el("status").textContent="下次识图将使用 "+config.model+"。";
  };
  el("run").onclick=analyze;
  async function analyze(){
    const nonce=++epoch;clear();el("run").disabled=true;el("status").textContent="视觉模型正在辨认端子与连线…";
    try{const form=modelFields(config);form.append("image",file);const data=await post(dialog.dataset.api,{body:form});
      if(nonce!==epoch)return;doc=data.netlist;
      pages=data.panels || [data.panel];
      equivalent=data.equivalent;el("plan-option").hidden=!equivalent;
      displayPage(0);
      const networks = data.observations || [];
      el("networks").hidden = !networks.length;
      el("network-list").replaceChildren(...networks.map(net => {
        const item = document.createElement("li");
        item.textContent = net.line + " · " + net.ends.map((ref, i) =>
          ref + " → " + (net.pins[i] ? pinName(net.pins[i]) : "未映射")).join("，");
        return item;
      }));

    }catch(e){if(nonce===epoch)el("status").textContent=e.message;}
    finally{if(nonce===epoch)el("run").disabled=!file;}
  }
  el("demo").onclick=async()=>{
    const nonce=++epoch;clear();el("file").value="";file=null;el("run").disabled=true;
    setSource(dialog.dataset.sample);
    el("status").textContent="正在读取星三角原图的示例…";
    try{const [a,b]=await Promise.all([fetch(dialog.dataset.reference),fetch(dialog.dataset.sample)]);
      if(!a.ok||!b.ok)throw Error("示例读取失败");
      const reference=await a.json(),blob=await b.blob();if(nonce!==epoch)return;
      doc=reference;file=new File([blob],"example.png",{type:"image/png"});el("run").disabled=false;await renderDiagram(reference);
    }catch(e){if(nonce===epoch)el("status").textContent=e.message;}
  };
  if (location.hash === "#circuit-example") {
    openCard();
    el("demo").click();
  }
})();
