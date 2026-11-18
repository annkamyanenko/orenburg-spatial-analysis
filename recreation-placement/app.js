"use strict";

const $ = id => document.getElementById(id);
const cityData = window.ORENBURG;
const modes = {walk:"Пешком", transit:"Автомобиль"};
const number = new Intl.NumberFormat("ru-RU", {maximumFractionDigits:1});
const fmt = value => value == null ? "Нет данных" : number.format(value);
const percentage = (deficit,demand) => deficit == null || !demand ? "Нет данных" : fmt(100*(1-deficit/demand))+" %";
const area = val => val == null ? "Нет данных" : fmt(val)+" м²";
const collection = features => ({type:"FeatureCollection",features});
const el = (tag, text, cls) => {
  const node=document.createElement(tag);
  if(text!=null) node.textContent=text;
  if(cls) node.className=cls;
  return node;
};
async function query(path, body) {
  const response=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok) throw new Error(result.error || "Ошибка локального сервера");
  return result;
}
const storageKey="orenburg-practice3-"+cityData.signature;
function readSaved() {
  try {return JSON.parse(localStorage.getItem(storageKey)||"[]");}
  catch {return [];}
}

async function main() {
  const base = await query("/api/base");
  let mode="walk", view="base", objects=[], result=null, ranking=null, selected=null, busy=false, zones=null;
  let saved=readSaved();
  const setStatus=message=>{$("status").textContent=message;};
  const current=()=>result??base[mode];
  const byBlock=new Map(cityData.blocks.map(f=>[f.properties.block_id,f]));
  const map=L.map("map",{preferCanvas:true,zoomControl:false});
  L.control.zoom({position:"topright",zoomInTitle:"Увеличить масштаб",zoomOutTitle:"Уменьшить масштаб"}).addTo(map);
  L.control.scale({imperial:false}).addTo(map);
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution('<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap</a>');
  const pane=(name,z,svg=false)=>{
    map.createPane(name).style.zIndex=z;
    return (svg?L.svg:L.canvas)({pane:name,padding:.25});
  };
  const background=pane("local",240), blocksRenderer=pane("blocks",350), visual=pane("visual",370,true);
  const linesRenderer=pane("walklines",330), selectionRenderer=pane("selection",410,true);
  map.getPane("walklines").style.pointerEvents="none";
  map.getPane("selection").style.pointerEvents="none";
  const bounds=L.geoJSON(collection(cityData.layers.city)).getBounds();
  const fit=()=>map.fitBounds(bounds,{padding:[18,18]});
  $("fit").onclick=fit;
  for(const button of document.querySelectorAll("[data-panel]")) {
    button.onclick=()=>{
      const id=button.dataset.panel;
      $(id).hidden=!$(id).hidden;
      document.querySelector('.reopen[data-panel="'+id+'"]').hidden=!$(id).hidden;
      map.invalidateSize();
    };
  }
  $("method-open").onclick=()=>$("method").showModal();
  let backgroundLayer;
  function changeBase() {
    if(backgroundLayer)map.removeLayer(backgroundLayer);
    const value=$("base").value;
    $("map").classList.toggle("light",value==="light");
    $("map-status").textContent="";
    if(value==="none")return;
    if(value==="satellite"){
      const item=window.ORENBURG_SATELLITE;
      backgroundLayer=L.tileLayer(item.url,{attribution:item.attribution,maxNativeZoom:item.maxNativeZoom});
      $("map-status").textContent=item.description;
      backgroundLayer.on("tileerror",()=>{$("map-status").textContent="Тайлы NASA недоступны. Выберите локальную подложку.";});
    }else{
      const light=value==="light";
      backgroundLayer=L.layerGroup(Object.entries({city:light?"#d3d1c9":"#2a2a2c",
        water:light?"#84a5bb":"#354d63",green:light?"#aebba2":"#38453a",barriers:light?"#b2a69a":"#48474b"})
        .map(([key,color])=>L.geoJSON(collection(cityData.layers[key]),{renderer:background,
          interactive:false,style:{color,fillColor:color,weight:1,fillOpacity:.65}})));
    }
    backgroundLayer.addTo(map);
  }
  $("base").onchange=changeBase;
  const overlaySettings={
    green:["Зелёные территории","#b6d38b"],water:["Водоёмы и реки","#8dafce"],
    riparian:["Условный приречной буфер","#a69bca"],resources:["Существующие рекреационные объекты","#b6d38b"],
    entrances:["Зарегистрированные и потенциальные входы","#dcc18b"],
    barriers:["Пространственные барьеры","#c38078"],bridges:["Мосты","#dcc18b"],
    walking:["Пешеходные связи","#8dafce"],zones:["Функциональные зоны генплана","#a69bca"]
  };
  const overlays={}, checks={};
  function overlay(key,source) {
    const color=overlaySettings[key][1];
    return L.geoJSON(source,{renderer:key==="walking"?linesRenderer:visual,interactive:key!=="walking",
      style:{color,fillColor:color,weight:key==="walking"?1:1.3,opacity:key==="walking"?.65:.8,fillOpacity:.16},
      pointToLayer:(feature,ll)=>L.circleMarker(ll,{renderer:visual,radius:3.5,weight:1,fillOpacity:.9,
        color:feature.properties.entrance_kind==="observed"?"#8dafce":"#dcc18b"}),
      onEachFeature(feature,layer){
        if(key==="walking")return;
        const d=feature.properties||{};
        if(feature.geometry.type.endsWith("Polygon")) layer.options.className="overlay-outline-hit";
        const label=key==="entrances"?(d.entrance_kind==="observed"?"Зарегистрированный вход":"Потенциальный вход"):
          d.zone_name || d.name || d.kind || overlaySettings[key][0];
        layer.bindTooltip(el("span",label));
      }});
  }
  async function toggle(key) {
    try {
      if(!checks[key].checked) {if(overlays[key])map.removeLayer(overlays[key]);return;}
      if(!overlays[key]){
        const source=key==="walking"?await query("/walking.geojson"):key==="zones"?zones:collection(cityData.layers[key]);
        if(!source){checks[key].checked=false;return;}
        overlays[key]=overlay(key,source);
      }
      if(checks[key].checked)overlays[key].addTo(map);
    }catch(error){checks[key].checked=false;setStatus(error.message);}
  }
  for(const [key,[name,color]] of Object.entries(overlaySettings)){
    const row=el("div",null,"layer-item"), label=el("label"), check=el("input"), swatch=el("span",null,"swatch");
    check.type="checkbox";check.checked=["green","water","resources"].includes(key);check.onchange=()=>toggle(key);
    if(key==="zones")check.disabled=true;
    checks[key]=check;swatch.style.setProperty("--swatch",color);
    label.append(check,swatch,el("span",name));row.append(label);$("layer-controls").append(row);
  }
  function loadZones(value) {
    if (value?.type!=="FeatureCollection" || !Array.isArray(value.features) || !value.features.length ||
        value.features.some(f=>!["Polygon","MultiPolygon"].includes(f.geometry?.type))) {
      throw Error("Нужен GeoJSON FeatureCollection с полигонами функциональных зон в WGS 84");
    }
    zones=value;
    if(overlays.zones) {map.removeLayer(overlays.zones);delete overlays.zones;}
    checks.zones.disabled=false;checks.zones.checked=true;toggle("zones");
    $("zone-note").textContent="Подключено объектов: "+fmt(value.features.length);
  }
  $("zones").onchange=async()=>{
    const file=$("zones").files[0];
    if(file)try{loadZones(JSON.parse(await file.text()));}catch(error){$("zone-note").textContent=error.message;}
  };
  fetch("/functional-zones.geojson").then(response=>response.ok?response.json():null)
    .then(value=>{if(value)loadZones(value);}).catch(error=>{$("zone-note").textContent=error.message;});

  const ranges=[
    ["0", "#566078"],["1–5000","#8dafce"],["5001–20 000","#dcc18b"],["Более 20 000","#c38078"],["Нет данных","#62626a"]
  ];
  const differences=[["Дефицит вырос","#c38078"],["Без изменения","#566078"],
    ["Сокращение 1–500 м²","#8dafce"],["Сокращение более 500 м²","#b6d38b"],["Нет данных","#62626a"]];
  const rowFor=id=>current().rows[id];
  function classIndex(value) {
    if(value==null)return 4;
    if(view==="change")return value<0?0:value===0?1:value<=500?2:3;
    return value===0?0:value<=5000?1:value<=20000?2:3;
  }
  const activeValue=row=>row[{base:2,scenario:3,change:4}[view]];
  function blockStyle(feature) {
    const palette=view==="change"?differences:ranges;
    return {color:"#96989e",weight:.6,opacity:.8,fillOpacity:.77,
      fillColor:palette[classIndex(activeValue(rowFor(feature.properties.block_id)))][1]};
  }
  const quarters=L.geoJSON(collection(cityData.blocks),{renderer:blocksRenderer,style:blockStyle,
    onEachFeature(feature,layer){
      const id=feature.properties.block_id;
      layer.on("click",()=>select(id));
      layer.bindTooltip(()=>el("span","Квартал "+id+" · "+area(activeValue(rowFor(id)))));
    }}).addTo(map);
  let selectionOutline,objectMarkers=L.layerGroup().addTo(map);
  function select(id,zoom=false) {
    selected=id;
    if(selectionOutline)map.removeLayer(selectionOutline);
    if(id!==null){
      selectionOutline=L.geoJSON(byBlock.get(id),{renderer:selectionRenderer,interactive:false,
        style:{color:"#f0f0f0",weight:2.5,fill:false}}).addTo(map);
      if(zoom)map.fitBounds(selectionOutline.getBounds(),{maxZoom:15,padding:[35,35]});
    }
    selection();controls();
  }
  $("clear-selection").onclick=()=>select(null);
  function selection(){
    $("selection").hidden=selected===null;
    if(selected===null)return;
    const d=byBlock.get(selected).properties,row=rowFor(selected);
    $("selected-title").textContent="Квартал "+selected;
    const values=[["Население",fmt(d.population)],["Расчётный спрос",area(row[1])],
      ["Новая площадь",area(objects.filter(o=>o.block===selected&&validArea(o.area)).reduce((total,o)=>total+Number(o.area),0))],
      ["Удовлетворено в базе",percentage(row[2],row[1])],["Удовлетворено в сценарии",percentage(row[3],row[1])],
      ["Исходный дефицит",area(row[2])],["Дефицит в сценарии",area(row[3])],["Сокращение",area(row[4])]];
    $("details").replaceChildren(...values.flatMap(([key,value])=>[el("dt",key),el("dd",value)]));
  }
  function viewTo(value) {view=value;render();}
  for(const button of document.querySelectorAll("[data-view]"))button.onclick=()=>viewTo(button.dataset.view);
  function stat(label,value){
    const card=el("article",null,"stat");card.append(el("strong",value),el("span",label));return card;
  }
  function render(){
    for(const button of document.querySelectorAll("[data-view]"))button.setAttribute("aria-current",String(view===button.dataset.view));
    quarters.setStyle(blockStyle);
    objectMarkers.clearLayers();
    if(view!=="base" && result)for(const item of result.objects)if(item.point){
      L.circleMarker(item.point,{renderer:visual,radius:7,weight:2,color:item.bound?"#b6d38b":"#c38078",fillOpacity:.85})
        .bindTooltip(el("span","Условный вход · "+area(item.area)+(item.bound?"":" · вне привязки"))).addTo(objectMarkers);
    }
    $("legend-title").textContent=view==="change"?"Сокращение дефицита, м²":"Остаточный дефицит, м²";
    $("legend").replaceChildren(...(view==="change"?differences:ranges).map(([text,color])=>{
      const row=el("div",null,"legend-row"),swatch=el("span",null,"swatch");swatch.style.setProperty("--swatch",color);
      row.append(swatch,el("span",text));return row;
    }));
    const r=current();
    $("cards").replaceChildren(stat("Добавлено",area(r.area)),stat("Ресурс сети",area(r.inventory+r.area)),
      stat("Удовлетворено · база",percentage(r.baseline_deficit,r.demand)),
      stat("Удовлетворено · сценарий",percentage(r.deficit,r.demand)),
      stat("Остаточный дефицит",area(r.deficit)),stat("Сокращение дефицита",area(r.gain)));
    selection();controls();quarterTable();
  }
  function validArea(value){return /^[0-9]+$/.test(String(value))&&Number.isSafeInteger(Number(value))&&Number(value)>0;}
  function settings(){
    const preset=$("preset").value;
    return {count:preset==="B"?2:1,area:preset==="B"?3000:6000};
  }
  function controls(){
    $("add").disabled=busy||selected===null||objects.length>=settings().count;
    $("calculate").disabled=busy||!objects.length||objects.some(o=>!validArea(o.area));
    $("auto").disabled=busy||!validArea($("area").value);
    $("save").disabled=busy||!result;
    for(const id of ["preset","mode","reset","area"])$(id).disabled=busy;
    for(const input of $("objects").querySelectorAll("input,button"))input.disabled=busy;
  }
  function invalidate(){
    result=null;view="base";render();
  }
  function listObjects(){
    $("objects").replaceChildren(...objects.map((item,i)=>{
      const row=el("div",null,"object-row"),input=el("input"),remove=el("button","×","icon");
      input.type="number";input.min=1;input.step=1;input.value=item.area;
      input.setAttribute("aria-label","Площадь объекта "+(i+1)+", м²");
      input.oninput=()=>{item.area=input.value;invalidate();if(!validArea(item.area))setStatus("Введите положительное целое число.");};
      remove.setAttribute("aria-label","Удалить объект "+(i+1));remove.onclick=()=>{objects.splice(i,1);listObjects();invalidate();};
      row.append(el("span","Кв. "+item.block),input,remove);return row;
    }));
    controls();
  }
  function presetNote(){
    $("preset-note").textContent={A:"Выберите квартал с учётом слоя функциональных зон. При отсутствии слоя укажите это в обосновании.",
      B:"Выберите два квартала, сопоставив зелёный каркас, возможные связи и барьеры.",
      V:"Перебор оценивает один объект независимо от ручных изменений."}[$("preset").value];
  }
  $("preset").onchange=()=>{objects=[];$("reason").value="";presetNote();listObjects();invalidate();};
  $("mode").onchange=()=>{mode=$("mode").value;ranking=null;rankTable();invalidate();setStatus("");};
  $("area").oninput=()=>{
    if(!validArea($("area").value))setStatus("Для перебора требуется положительная целая площадь.");
    controls();
  };
  $("add").onclick=()=>{
    if(selected!==null&&objects.length<settings().count){
      objects.push({block:selected,area:settings().area});listObjects();invalidate();
    }
  };
  function setBusy(value) {busy=value;controls();}
  async function task(path,body) {
    const {job}=await query(path,body);
    while(true){
      const status=await query("/api/jobs/"+job);
      if(status.status==="done")return status.result;
      if(status.status==="error")throw Error(status.error);
      if(path.endsWith("rank")){
        $("progress").max=status.total;$("progress").value=status.checked;
        setStatus("Проверено "+fmt(status.checked)+" из "+fmt(status.total)+" кварталов");
      }
      await new Promise(resolve=>setTimeout(resolve,350));
    }
  }
  function applied(value) {
    result=value;view="scenario";render();
  }
  async function runScenario(){
    setBusy(true);setStatus("Расчёт сценария…");
    try{
      applied(await task("/api/scenario",{mode,objects:objects.map(o=>({block:o.block,area:Number(o.area)}))}));
      const skipped=result.objects.filter(o=>!o.bound).length;
      setStatus(skipped?"Готово. Вне привязки объектов: "+fmt(skipped):"Сценарий рассчитан.");
    }catch(error){setStatus(error.message);}
    finally{setBusy(false);}
  }
  $("calculate").onclick=runScenario;
  async function chooseRank(item) {
    if(busy||item.status!=="calculated")return;
    $("preset").value="V";presetNote();$("reason").value="Автоматический подбор по сокращению дефицита.";
    objects=[{block:item.block,area:ranking.area}];listObjects();select(item.block,true);
    await runScenario();
    if(result && result.gain!==item.gain)setStatus("Результаты ручного и автоматического расчёта различаются.");
  }
  $("auto").onclick=async()=>{
    setBusy(true);setStatus("Подготовка сетевых связей…");$("progress").hidden=false;$("progress").removeAttribute("value");
    try{
      ranking=await task("/api/rank",{mode,area:Number($("area").value)});
      $("rank-details").open=true;rankTable();
      setStatus(ranking.complete?"Все кварталы рассмотрены.":"Перебор неполный. Проверьте статусы вариантов.");
    }catch(error){setStatus(error.message);}
    finally{$("progress").hidden=true;setBusy(false);}
    if(ranking?.complete&&ranking.best.length)await chooseRank(ranking.rows[0]);
  };
  $("reset").onclick=()=>{
    objects=[];result=null;ranking=null;view="base";$("reason").value="";$("area").value="6000";
    $("preset").value="A";presetNote();select(null);listObjects();rankTable();render();fit();setStatus("Исходное состояние восстановлено.");
  };

  function table(id, headers, rows) {
    const head=el("thead"), tr=el("tr"), body=el("tbody");
    tr.append(...headers.map(h=>el("th",h)));head.append(tr);
    for(const row of rows){
      const line=el("tr");
      for(const value of row){
        const cell=el("td");
        cell.append(value instanceof Node?value:document.createTextNode(String(value)));
        line.append(cell);
      }
      body.append(line);
    }
    $(id).replaceChildren(head,body);
  }
  function link(label,action){
    const button=el("button",label,"table-action");button.onclick=action;return button;
  }
  function quarterTable(){
    if(!$("quarters").closest("details").open)return;
    table("quarters",["Квартал","Спрос, м²","В базе, %","В сценарии, %","Дефицит в базе, м²","Остаток, м²","Сокращение, м²"],
      current().rows.map(row=>[link(row[0],()=>select(row[0],true)),fmt(row[1]),percentage(row[2],row[1]),
        percentage(row[3],row[1]),fmt(row[2]),fmt(row[3]),fmt(row[4])]));
  }
  $("quarters").closest("details").ontoggle=quarterTable;
  const statusNames={calculated:"Рассчитан",unbound:"Вне привязки",failed:"Не рассчитан"};
  function rankTable(){
    $("rank-export").disabled=!ranking;
    if(!ranking){$("ranking").replaceChildren();$("rank-status").textContent="Запустите автоматический подбор.";return;}
    const best=new Set(ranking.best);
    const count=status=>ranking.rows.filter(r=>r.status===status).length;
    $("rank-status").textContent="Рассмотрено "+fmt(ranking.rows.length)+" из "+fmt(ranking.total)+
      ". Рассчитано: "+fmt(count("calculated"))+". Вне привязки: "+fmt(count("unbound"))+
      ". Ошибки: "+fmt(count("failed"))+". "+(ranking.complete?"Равноценных лучших: ":"Равноценных среди рассчитанных: ")+fmt(best.size)+".";
    table("ranking",["Квартал","Сокращение, м²","Статус"],ranking.rows.map(r=>[
      r.status==="calculated"?link(r.block,()=>chooseRank(r)):r.block,fmt(r.gain),
      best.has(r.block)?el("strong",ranking.complete?"Лучший":"Лучший из рассчитанных","best"):
        r.error?statusNames[r.status]+" · "+r.error:statusNames[r.status]]));
  }
  function showSaved(item){
    if(busy)return;
    mode=item.value.mode;$("mode").value=mode;
    ranking=null;rankTable();
    $("preset").value=item.preset;presetNote();$("reason").value=item.reason;
    objects=item.value.objects.map(o=>({block:o.block,area:o.area}));listObjects();applied(item.value);
  }
  function comparison(){
    const items=[{name:"База · Пешком",value:base.walk},{name:"База · Автомобиль",value:base.transit},...saved];
    table("comparison",["Сценарий","Режим","Объекты","Добавлено, м²","Удовлетворено","Дефицит, м²","Сокращение, м²","Обоснование"],
      items.map(item=>[item.preset?link(item.name,()=>showSaved(item)):item.name,modes[item.value.mode],
        item.value.objects.map(o=>o.block+" ("+fmt(o.area)+" м²)").join(", ")||"—",fmt(item.value.area),
        percentage(item.value.deficit,item.value.demand),fmt(item.value.deficit),fmt(item.value.gain),item.reason||"—"]));
  }
  $("save").onclick=()=>{
    if(!result)return;
    const prefix={A:"А",B:"Б",V:"В"}[$("preset").value];
    const next=[...saved,{name:prefix+" · "+(saved.length+1),preset:$("preset").value,reason:$("reason").value,value:result}];
    try{localStorage.setItem(storageKey,JSON.stringify(next));saved=next;comparison();setStatus("Сценарий сохранён в этом браузере.");}
    catch{setStatus("Хранилище браузера заполнено. Экспортируйте сценарий в CSV.");}
  };
  function csv(file,head,rows){
    const cell=value=>'"'+String(value??"").replaceAll('"','""')+'"';
    const blob=new Blob(["\ufeff",[head,...rows].map(row=>row.map(cell).join(";")).join("\r\n")],
      {type:"text/csv;charset=utf-8"});
    const url=URL.createObjectURL(blob),anchor=el("a");
    anchor.href=url;anchor.download=file;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
  }
  $("export").onclick=()=>csv("orenburg-scenario-"+mode+".csv",
    ["Квартал","Спрос м²","Дефицит база м²","Дефицит сценарий м²","Сокращение м²","Удовлетворено база доля","Удовлетворено сценарий доля"],
    current().rows.map(row=>[...row,row[2]==null||!row[1]?null:1-row[2]/row[1],row[3]==null||!row[1]?null:1-row[3]/row[1]]));
  $("rank-export").onclick=()=>{if(ranking)csv("orenburg-ranking-"+ranking.mode+".csv",["Квартал","Сокращение м²","Статус","Лучший из рассчитанных"],
    ranking.rows.map(r=>[r.block,r.gain,statusNames[r.status],ranking.best.includes(r.block)?"Да":""]));};
  for(const key of Object.keys(checks))if(checks[key].checked)toggle(key);
  changeBase();fit();presetNote();listObjects();rankTable();comparison();render();
}

main().catch(error=>{$("status").textContent="Ошибка запуска: "+error.message;});
