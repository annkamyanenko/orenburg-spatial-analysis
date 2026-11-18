"use strict";

const $ = id => document.getElementById(id);
const data = window.ORENBURG;
const missing = "#66666b";
const colors = ["#596477", "#8dafce", "#b6d38b", "#dcc18b", "#c38078", "#a69bca", "#d9a7bc", "#7ab4ad"];
const scale = ["#3f526d", "#607e9e", "#8dafce", "#b6c9a0", "#dcc18b"];
const numeric = value => typeof value === "number" && Number.isFinite(value);
const fmt = (value, digits = 0) => numeric(value)
  ? new Intl.NumberFormat("ru-RU", {maximumFractionDigits: digits}).format(value) : "Нет данных";
const percent = value => numeric(value) ? fmt(value * 100, 1) + " %" : "Нет данных";
const median = values => {
  const ordered = values.filter(numeric).sort((a, b) => a - b);
  const i = Math.floor(ordered.length / 2);
  return ordered.length ? (ordered[i] + ordered[Math.floor((ordered.length - 1) / 2)]) / 2 : null;
};
const props = data?.blocks.map(feature => feature.properties) ?? [];
// The export uses zero reachable area for destinations outside the snap threshold.
// At block level this is a network coverage gap, so use a separate missing class.
const displayValue = (item, key) => key === "reachable_area_share" && !item.transport_bound ? null : item[key];
const medianOf = field => median(props.map(d => d[field]));
const landNames = {residential:"Жилое", business:"Деловое", recreation:"Рекреационное", industrial:"Промышленное", transport:"Транспортное", special:"Специальное", agriculture:"Сельскохозяйственное"};
const morphWords = {"low-rise":"Малоэтажный", "mid-rise":"Среднеэтажный", "high-mid-rise":"Повышенной этажности", "high-rise":"Высотный", tower:"Башенный", "low-density":"низкой плотности", "high-density":"высокой плотности", "non-residential":"нежилой", "mixed-use":"смешанный", residential:"жилой"};
const strelkaNames = {"low-rise non-residential":"Малоэтажная нежилая", "individual residential":"Индивидуальная жилая", "low-rise model":"Малоэтажная модель", "mid-rise":"Среднеэтажная", "mid-rise non-residential":"Среднеэтажная нежилая", "mid-rise microdistrict":"Среднеэтажный микрорайон", "mid-rise block":"Среднеэтажный квартал", "central model":"Центральная модель", "high-rise non-residential":"Высотная нежилая", "high-rise soviet microdistrict":"Советский высотный микрорайон", "high-rise modern microdistrict":"Современный высотный микрорайон"};
const num = (name, unit, digits = 1, ratio = false) => ({name, print: value => {
  if (!numeric(value)) return "Нет данных";
  return ratio ? percent(value) : [fmt(value, digits), unit].filter(Boolean).join(" ");
}});
const cat = (name, label) => ({name, label, print: value => value == null ? "Нет данных" : label(value)});
const share = name => num(name, "%", 1, true);
const metrics = {
  population_ha:num("Плотность населения", "чел./га"), population:num("Население после калибровки", "чел.", 0),
  population_original:num("Исходная оценка населения", "чел.", 0),
  fsi:num("Интенсивность застройки · FSI", "м²/м²", 2), gsi:share("Доля пятен зданий · GSI"), l:num("Средняя этажность", "эт."), mxi:share("Жилая доля поэтажной площади"),
  osr:num("Свободная площадь на м² поэтажной площади · OSR", "м²/м²", 2),
  share_living:num("Жилая площадь на м² пятен зданий", "м²/м²", 2),
  share_non_living:num("Нежилая площадь на м² пятен зданий", "м²/м²", 2),
  spacematrix:cat("Морфотип Spacematrix", v => v.split(" ").map(word => morphWords[word] || word).join(" ")),
  strelka:cat("Морфотип Strelka", v => strelkaNames[v] || v),
  land_use:cat("Преобладающее землепользование", v => landNames[v] || v), land_use_unknown:share("Неизвестное использование площади"),
  green_share:share("Доля зелёных территорий"), riparian_share:share("Доля условной приречной зоны"),
  attractor_count:num("Потенциально значимые объекты", "объектов", 0), attractors_km2:num("Концентрация объектов", "объектов/км²"),
  transport_bound:cat("Привязка к автомобильной сети", v => v ? "Привязан" : "Вне порога"),
  transport_snap_m:num("Расстояние до узла автомобильной сети", "м", 0),
  walk_nearest:num("До входа пешком в пределах порога", "м", 0),
  transit_nearest:num("До входа на автомобиле в пределах порога", "мин"),
  reachable_area_share:share("Достижимая доля всей площади кварталов"),
  reachable_bound_area_share:share("Достижимая доля привязанной площади"),
  reachable_area_time_min:num("Среднее время до достижимой площади", "мин"),
  walk_satisfied:share("Удовлетворение потребности · пешком"), transit_satisfied:share("Удовлетворение потребности · автомобиль"),
  walk_deficit_m2:num("Расчётный дефицит · пешком", "м²", 0), transit_deficit_m2:num("Расчётный дефицит · автомобиль", "м²", 0),
  local_m2_person:num("Площадь внутри квартала на жителя", "м²/чел.", 2),
  riparian:cat("Группа квартала", v => v ? "Приречные" : "Остальные")
};
const layerInfo = {
  blocks:["Кварталы", "#8dafce"], city:["Городской контур", "#d2d2d3"], water:["Вода", "#8dafce"],
  green:["Зелёные территории", "#b6d38b"], riparian:["Приречный буфер", "#a69bca"],
  attractors:["Потенциально значимые объекты", "#dcc18b"], barriers:["Барьеры", "#c38078"],
  bridges:["Мосты", "#dcc18b"], crossings:["Переходы", "#a69bca"],
  resources:["Рекреационные территории", "#b6d38b"], entrances:["Точки доступа", "#dcc18b"]
};
const categoryColors = {"Историко-культурный":"#dcc18b","Природный":"#b6d38b","Видовой или туристический":"#a69bca","Рекреационный":"#8dafce"};
const barrierColors = {"Магистраль":"#c38078","Железная дорога":"#dcc18b","Водный объект":"#8dafce"};
const stat = (name, value) => ({name, value});
const diag = data?.diagnostics;
const summary = data?.summary;
const total = name => data.layers[name].length;
const km2 = squareMeters => fmt(squareMeters / 1e6, 2) + " км²";
const sum = field => props.reduce((result, item) => result + item[field], 0);
const section = (label, title, note, fields, layers, cards) => ({label,title,note,fields,layers,cards});
const sections = [
  section("Обзор","Оренбург","Кварталы города и условная приречная зона Урала и Сакмары.",["population_ha","population","population_original","riparian"],["water","riparian"],() => [
    stat("Кварталы",fmt(props.length)),stat("Население · калибр.",fmt(summary.population)),
    stat("Площадь кварталов",km2(sum("site_area"))),stat("Приречные кварталы",fmt(props.filter(d=>d.riparian).length))]),
  section("Морфология","Морфология и плотность","FSI — поэтажная площадь на м² квартала. GSI — доля пятен зданий. Этажность взвешена по пятнам.",["fsi","gsi","l","mxi","osr","share_living","share_non_living","spacematrix","strelka"],["water"],() => [
    stat("Медиана FSI",fmt(medianOf("fsi"),2)),stat("Медиана GSI",percent(medianOf("gsi"))),
    stat("Медианная этажность",metrics.l.print(medianOf("l"))),stat("С морфотипом",fmt(props.filter(d=>d.spacematrix!=null).length))]),
  section("Землепользование","Землепользование","Класс квартала соответствует крупнейшей выявленной доле по контурам OSM. Непокрытая площадь учитывается отдельно.",["land_use","land_use_unknown"],["water"],() => [
    stat("Определённый класс",fmt(props.filter(d=>d.land_use!=null).length)),
    stat("Класс неизвестен",fmt(props.filter(d=>d.land_use==null).length))]),
  section("Каркас","Водно-зелёный каркас","Зелёная доля вычислена по картографическим контурам. Приречная группа задана условным буфером.",["green_share","riparian_share","riparian"],["green","water","riparian"],() => [
    stat("Медиана зелёной доли",percent(medianOf("green_share"))),stat("Ширина буфера",fmt(data.parameters.riparian_buffer_m)+" м")]),
  section("Значимые объекты","Потенциально значимые пространственные объекты","Объекты из инвентаря OSM. Концентрация — число записей на км² квартала.",["attractors_km2","attractor_count"],["attractors","water","riparian"],() => [
    stat("Записей в инвентаре",fmt(total("attractors"))),stat("Записей отнесено к кварталам",fmt(sum("attractor_count")))]),
  section("Барьеры","Пространственные барьеры","Магистрали, железные дороги и вода рассматриваются как потенциальные барьеры. Мосты и переходы показывают возможные пересечения.",["riparian","transport_snap_m"],["barriers","bridges","crossings","water"],() => [
    stat("Записей барьеров",fmt(total("barriers"))),stat("Записей мостов",fmt(total("bridges"))),
    stat("Записей переходов",fmt(total("crossings")))]),
  section("Доступность","Пешеходная и автомобильная доступность","Пеший маршрут измеряется в метрах. Автомобильное время расчётное. Кварталы без привязки выделены отдельно. Общегородская медиана сохранена из источника, где для них записан ноль.",["reachable_area_share","reachable_bound_area_share","reachable_area_time_min","walk_nearest","transit_nearest","transport_bound","transport_snap_m"],["water","entrances"],() => [
    stat("Привязано кварталов",fmt(diag.blocks_bound)+" / "+fmt(diag.blocks_total)),stat("Привязанная площадь",percent(diag.bound_area_share)),
    stat("Медиана от всей площади",percent(diag.median_reachable_area_share)),stat("Медиана среди привязанных",percent(diag.median_reachable_bound_area_share))]),
  section("Рекреация","Рекреационная обеспеченность","В модели конкуренции площадь распределяется в пределах порога выбранной сети. Потенциальные входы требуют проверки.",["walk_satisfied","transit_satisfied","walk_deficit_m2","transit_deficit_m2","local_m2_person","walk_nearest","transit_nearest"],["resources","entrances","water"],() => [
    stat("Выявлено на жителя",fmt(summary.per_person,2)+" м²"),stat("Рабочая норма",fmt(data.parameters.recreation_m2_person)+" м²/чел."),
    stat("Зарегистрированные входы",fmt(summary.observed)),stat("Потенциальные входы",fmt(summary.potential))]),
  section("Сравнение","Приречные и остальные кварталы","Группы выделены по доле пересечения квартала с условным буфером. Сравнение носит описательный характер.",["riparian","population_ha","fsi","green_share","attractors_km2","walk_satisfied","transit_satisfied"],["riparian","water"],() => data.groups.map(group=>stat(group.group+" · кварталы",fmt(group.blocks))))
];

function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text != null) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function classification(field) {
  const metric = metrics[field];
  const values = props.map(p => displayValue(p,field)).filter(v => v != null);
  let index, classes;
  if (metric.label) {
    const categories = [...new Set(values)].sort((a,b) => metric.label(a).localeCompare(metric.label(b),"ru"));
    index = value => categories.indexOf(value);
    classes = categories.map((value, i) => ({label:metric.label(value), color:colors[i % colors.length]}));
  } else {
    values.sort((a,b)=>a-b);
    const min = values[0], max = values.at(-1);
    const thresholds = [...new Set([.2,.4,.6,.8].map(p=>values[Math.floor(p*(values.length-1))]))].filter(x=>x<max);
    index = value => thresholds.findIndex(limit => value <= limit) + 1 || thresholds.length + 1;
    const bounds = [...thresholds,max];
    classes = values.length ? bounds.map((limit,i)=>({
      label:min === max ? metric.print(limit) : (i ? "> " + metric.print(bounds[i-1]) : "≥ " + metric.print(min)) + " — " + metric.print(limit),
      color:scale[Math.round(i*4 / Math.max(1,bounds.length-1))]
    })) : [];
    const oneBased = index;
    index = value => oneBased(value) - 1;
  }
  const noData = classes.length;
  classes.push({label:"Нет данных",color:missing});
  return {classes, index:value=>value==null ? noData : index(value)};
}

function start() {
  if (!data || !window.L) {
    $("map-status").textContent = "Не удалось загрузить данные или Leaflet. Проверьте комплект файлов дашборда.";
    return;
  }
  const map = L.map("map", {zoomControl:false, preferCanvas:true, minZoom:8, maxZoom:18});
  const zoom = L.control.zoom({position:"topright",zoomInTitle:"Увеличить масштаб",zoomOutTitle:"Уменьшить масштаб"}).addTo(map);
  zoom.getContainer().querySelector(".leaflet-control-zoom-in").setAttribute("aria-label","Увеличить масштаб");
  zoom.getContainer().querySelector(".leaflet-control-zoom-out").setAttribute("aria-label","Уменьшить масштаб");
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution('<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap</a>');
  L.control.scale({imperial:false,position:"bottomleft"}).addTo(map);
  const attribution = map.attributionControl.getContainer();
  attribution.setAttribute("aria-label","Источники карты");
  const pane = (name,z,svg=false,interactive=true) => {
    const element=map.createPane(name);
    element.style.zIndex=z;
    if (!interactive) element.style.pointerEvents="none";
    return (svg?L.svg:L.canvas)({pane:name,padding:.25});
  };
  const baseRenderer=pane("local",240,false,false), blockRenderer=pane("blocks",350);
  // SVG hit-testing on overlay paths leaves uncovered canvas pixels accessible to quarters.
  const areaRenderer=pane("areas",360,true), pointRenderer=pane("points",390,true);
  const selectRenderer=pane("select",420,true,false);
  const fc = features=>({type:"FeatureCollection",features});
  const bounds = L.geoJSON(fc(data.layers.city)).getBounds();
  const fit = () => map.fitBounds(bounds,{padding:[18,18]});
  $("fit").onclick=fit;
  for (const button of document.querySelectorAll("[data-panel]")) {
    button.onclick=()=>{
      const panel=$(button.dataset.panel);
      panel.hidden=!panel.hidden;
      document.querySelector(".reopen[data-panel="+button.dataset.panel+"]").hidden=!panel.hidden;
      map.invalidateSize();
    };
  }
  $("method-open").onclick=()=>$("method").showModal();
  $("dataset").textContent="Выгрузка "+data.signature;
  const p=data.parameters;
  $("parameters").textContent = ["Буфер "+fmt(p.riparian_buffer_m)+" м","Привязка "+fmt(p.snap_limit_m)+" м","Пешком "+fmt(p.walk_limit_m)+" м","Автомобиль "+fmt(p.transport_limit_min)+" мин","Обеспеченность "+fmt(p.recreation_m2_person)+" м²/чел."].join(" · ");

  const opacity={blocks:.76,city:.85,water:.86,green:.65,riparian:.65,attractors:.93,barriers:.78,bridges:.93,crossings:.7,resources:.85,entrances:.95};
  const layers={}, toggles={};
  let active=0, field="population_ha", bins=classification(field), filter=null, selected=null;
  let outline, basemap;
  function blockStyle(feature) {
    const id=bins.index(displayValue(feature.properties,field));
    const alpha=opacity.blocks*(filter!==null && filter!==id ? .14 : 1);
    return {color:"#96989e",weight:.55,opacity:alpha*.8,fillColor:bins.classes[id]?.color??missing,fillOpacity:alpha};
  }
  function tooltip(text) { return node("span",text); }
  function selectBlock(feature) {
    selected=feature;
    if (outline) map.removeLayer(outline);
    outline=L.geoJSON(feature,{interactive:false,renderer:selectRenderer,style:{color:"#f6f3ec",weight:2,fill:false}}).addTo(map);
    renderSelection();
  }
  function renderSelection() {
    $("selection").hidden=!selected;
    if (!selected) return;
    const d=selected.properties;
    $("selected-title").textContent="Квартал "+d.block_id;
    const fields=[...new Set([field,"riparian","population","population_original","population_ha","land_use","l","walk_nearest","transit_nearest"])];
    const rows=[["Площадь",fmt(d.site_area/10000,2)+" га"],...fields.map(key=>[metrics[key].name,metrics[key].print(displayValue(d,key))])];
    $("details").replaceChildren(...rows.flatMap(([a,b])=>[node("dt",a),node("dd",b)]));
  }
  $("clear-selection").onclick=()=>{
    if (outline) map.removeLayer(outline);
    selected=null;
    renderSelection();
  };
  layers.blocks=L.geoJSON(fc(data.blocks),{renderer:blockRenderer,style:blockStyle,onEachFeature(feature,layer){
    layer.on("click",()=>selectBlock(feature));
    layer.bindTooltip(()=>tooltip("Квартал "+feature.properties.block_id+" · "+metrics[field].print(displayValue(feature.properties,field))));
  }}).addTo(map);

  function overlayColor(key,feature) {
    const d=feature.properties;
    if (key==="entrances") return d.entrance_kind==="observed"?"#8dafce":"#dcc18b";
    if (key==="attractors") return categoryColors[d.category]||missing;
    if (key==="barriers") return barrierColors[d.kind]||missing;
    return layerInfo[key][1];
  }
  function overlayStyle(key, feature) {
    const color=overlayColor(key,feature);
    return {color,fillColor:color,weight:key==="city"?1.4:1.3,opacity:opacity[key],fillOpacity:opacity[key]*(key==="city"?0:.45)};
  }
  function overlayLabel(key,d) {
    if(key==="entrances") return (d.entrance_kind==="observed"?"Зарегистрированный вход":"Потенциальный вход")+" · объект "+d.resource_id;
    if(key==="resources") return (d.name||"Рекреационная территория")+" · "+fmt(d.resource_area_m2,0)+" м²";
    return [d.name,d.category||d.kind||d.zone_type].filter(Boolean).join(" · ")||layerInfo[key][0];
  }
  function getOverlay(key) {
    if(!layers[key]) {
      layers[key]=L.geoJSON(fc(data.layers[key]),{renderer:areaRenderer,interactive:key!=="city",style:f=>overlayStyle(key,f),
        pointToLayer:(f,ll)=>L.circleMarker(ll,{renderer:pointRenderer,radius:key==="crossings"?2.5:4,weight:1}),
        onEachFeature(f,layer){
          if(f.geometry.type.endsWith("Polygon")) layer.options.className="overlay-outline-hit";
          if(key!=="city") layer.bindTooltip(tooltip(overlayLabel(key,f.properties)));
        }});
    }
    return layers[key];
  }
  function refreshOverlay(key) {
    if(key==="blocks") layers.blocks.setStyle(blockStyle);
    else if(layers[key]) layers[key].setStyle(f=>{
      const style=overlayStyle(key,f);
      if(f.geometry.type==="Point") style.fillOpacity=opacity[key];
      return style;
    });
  }
  function toggle(key, enabled) {
    toggles[key].checked=enabled;
    if(enabled) { (key==="blocks"?layers.blocks:getOverlay(key)).addTo(map); refreshOverlay(key); }
    else if(layers[key]) map.removeLayer(layers[key]);
    renderLegend();
  }
  for (const [key,[label,color]] of Object.entries(layerInfo)) {
    const row=node("div",null,"layer-item"), name=node("label");
    const check=node("input");check.type="checkbox";check.onchange=()=>toggle(key,check.checked);toggles[key]=check;
    name.append(check,swatch(color),node("span",label));
    const range=node("input");range.type="range";range.min=0;range.max=100;range.value=opacity[key]*100;
    range.setAttribute("aria-label","Непрозрачность: "+label);range.oninput=()=>{opacity[key]=Number(range.value)/100;refreshOverlay(key);};
    row.append(name,range);$("layer-controls").append(row);
  }
  function swatch(color) {const icon=node("span",null,"swatch");icon.style.setProperty("--swatch",color);return icon;}
  function legendRow(label,color) {const row=node("div",null,"legend-row");row.append(swatch(color),node("span",label));return row;}
  function renderLegend() {
    $("legend-title").textContent=toggles.blocks.checked?metrics[field].name:"Квартальный слой скрыт";
    const rows=toggles.blocks.checked?bins.classes.map(c=>legendRow(c.label,c.color)):[];
    for(const key of Object.keys(layerInfo).filter(k=>k!=="blocks"&&toggles[k].checked)) {
      const entries=key==="entrances"?{"Зарегистрированный вход":"#8dafce","Потенциальный вход":"#dcc18b"}:
        key==="attractors"?categoryColors:key==="barriers"?barrierColors:{[layerInfo[key][0]]:layerInfo[key][1]};
      rows.push(...Object.entries(entries).map(([label,color])=>legendRow(label,color)));
    }
    $("legend").replaceChildren(...rows);
  }
  function setBase(mode) {
    if(basemap) map.removeLayer(basemap);
    $("map").classList.toggle("light",mode==="light");
    $("map-status").textContent="";
    if(mode==="none") return;
    if(mode==="satellite") {
      const config=window.ORENBURG_SATELLITE;
      if(!config?.url || !config?.attribution) {
        $("base").value="none";
        $("map-status").textContent="Спутниковая подложка недоступна: подключите источник с разрешением и атрибуцией.";
        return;
      }
      basemap=L.tileLayer(config.url,{attribution:config.attribution,maxNativeZoom:config.maxNativeZoom??18});
      $("map-status").textContent=config.description||"";
      basemap.on("tileerror",()=>{$("map-status").textContent="Спутниковые тайлы не загрузились. Можно выбрать локальную подложку.";});
    } else {
      const light=mode==="light";
      basemap=L.layerGroup(Object.entries({city:light?"#d3d1c9":"#2a2a2c",water:light?"#84a5bb":"#354d63",
        green:light?"#aebba2":"#38453a",barriers:light?"#b2a69a":"#48474b"}).map(([key,color])=>
        L.geoJSON(fc(data.layers[key]),{renderer:baseRenderer,interactive:false,style:{color,fillColor:color,weight:key==="city"?1:.8,fillOpacity:.72,opacity:.92}})));
    }
    basemap.addTo(map);
  }
  $("base").onchange=()=>setBase($("base").value);

  function renderChart() {
    const metric=metrics[field], classes=bins.classes;
    const counts=classes.map(()=>0);
    for(const item of props) counts[bins.index(displayValue(item,field))]++;
    const max=Math.max(1,...counts);
    $("chart-title").textContent=active===8 && field==="riparian"?"Число кварталов по группам":"Распределение кварталов";
    $("chart-note").textContent=metric.name+". Выберите категорию, чтобы выделить её на карте.";
    $("chart").replaceChildren(...classes.map((c,i)=>{
      const button=node("button",null,"bar");button.type="button";button.setAttribute("aria-pressed",String(filter===i));
      button.title=fmt(counts[i])+" кварталов · "+percent(counts[i]/props.length);
      const label=node("span",null,"bar-title");label.append(node("span",c.label),node("strong",fmt(counts[i])));
      const track=node("span",null,"track"), fill=node("i");
      fill.style.width=counts[i]*100/max+"%";fill.style.setProperty("--bar",c.color);track.append(fill);
      button.append(label,track);
      button.onclick=()=>{
        filter=filter===i?null:i;
        for(const [j,bar] of [...$("chart").children].entries()) bar.setAttribute("aria-pressed",String(j===filter));
        refreshOverlay("blocks");
      };
      return button;
    }));
    if(active===8) {
      const table=node("div",null,"compare-table");
      for(const group of data.groups) {
        table.append(node("h3",group.group));
        table.append(node("p",fmt(group.population)+" чел. · "+fmt(group.population_ha_median,1)+" чел./га (медиана) · "+fmt(group.recreation_m2_person,2)+" м² рекреации/чел."));
      }
      $("chart").after(table);
    }
  }
  function setMetric(value) {
    field=value;bins=classification(field);filter=null;
    document.querySelector(".compare-table")?.remove();
    refreshOverlay("blocks");renderChart();renderLegend();renderSelection();
  }
  $("metric").onchange=()=>setMetric($("metric").value);
  const buttons = sections.map((s,index)=>{
    const button=node("button",s.label);button.type="button";button.title=s.title;button.onclick=()=>choose(index);return button;
  });
  $("sections").append(...buttons);
  function choose(index) {
    active=index;
    const current=sections[index];
    buttons.forEach((button,i)=>button.setAttribute("aria-current",String(i===index)));
    $("section-title").textContent=current.title;
    $("section-note").textContent=current.note;
    $("cards").replaceChildren(...current.cards().map((item,i)=>{
      const card=node("article",null,"stat");card.style.setProperty("--accent",["#b6d38b","#8dafce","#dcc18b","#a69bca"][i%4]);
      card.append(node("strong",item.value),node("span",item.name));return card;
    }));
    $("metric").replaceChildren(...current.fields.map(key=>new Option(metrics[key].name,key)));
    setMetric(current.fields[0]);
    const defaults=new Set(["blocks","city",...current.layers]);
    for(const key of Object.keys(layerInfo)) toggle(key,defaults.has(key));
  }
  choose(0);setBase("dark");fit();
}

start();
