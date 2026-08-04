import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const inputPath='C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx';
const outputDir='C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1';
const outputPath=`${outputDir}/文胸商品_分类TOP10_按主卖点_胸型双榜_2026-07.xlsx`;
await fs.mkdir(outputDir,{recursive:true});
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));

const oldCategorySheets=['日常TOP10','抹胸TOP10','前扣TOP10','束背TOP10','矫正TOP10','聚拢TOP10'];
const template=wb.worksheets.getItem('日常TOP10');
const templateRange=template.getRange('A1:X11');
const sourceRows=new Map();
const allRows=[];
const sourceCats=new Map();

for(const name of oldCategorySheets){
  const vals=wb.worksheets.getItem(name).getUsedRange().values;
  for(let i=1;i<vals.length;i++){
    const row=vals[i];
    if(!row[6]) continue;
    const id=String(row[7]);
    const rank=Number(row[4]);
    if(!sourceRows.has(id) || rank < Number(sourceRows.get(id).row[4])) sourceRows.set(id,{row:[...row],sheet:name});
    if(!sourceCats.has(id)) sourceCats.set(id,[]);
    sourceCats.get(id).push({sheet:name,row:[...row]});
  }
}

const tagOrder=['矫正','抹胸','前扣','束背','聚拢','日常','运动'];
const titleOf=id=>String(sourceRows.get(id)?.row?.[6]??'');
const explicitPrimary={
  // 用户已复核：该商品实物不按抹胸归类，归入聚拢/提拉
  '3826919824940990563':'聚拢',
};
function collectTags(id){
  const tags=new Set();
  for(const x of sourceCats.get(id)||[]){
    for(const t of String(x.row[19]??'').split('、').map(s=>s.trim()).filter(Boolean)) tags.add(t);
  }
  if(id==='3826919824940990563') tags.delete('抹胸');
  return tagOrder.filter(t=>tags.has(t));
}
function primaryFor(id,tags){
  if(explicitPrimary[id]) return explicitPrimary[id];
  const title=titleOf(id);
  if(tags.includes('矫正')) return '矫正';
  // 前扣是闭合结构卖点，优先于抹胸/聚拢/日常，避免同一商品重复进入多表。
  if(tags.includes('前扣') || /前扣/.test(title)) return '前扣';
  if(tags.includes('抹胸')) return '抹胸';
  if(tags.includes('束背')) return '束背';
  if(tags.includes('聚拢')) return '聚拢';
  return '日常';
}
const sizeMap={
  '3668622727843021221':['小胸','未出现大胸/小胸词；轻支撑、细肩带、隐形无痕定位，按小胸倾向'],
  '3747856469228388817':['大胸','未出现尺寸词；防滑、聚拢、可调节前扣强调承托，按大胸倾向'],
  '3805536475458699588':['大胸','详情含提拉/收副乳，属承托调整卖点，按大胸倾向'],
  '3830024278724706385':['小胸','轻塑、凉感、细肩带、日常轻薄定位，按小胸倾向'],
  '3830178603467931832':['大胸','详情含防外扩/收副乳/聚拢，按大胸支撑定位'],
  '3792494994254856675':['大胸','标题与详情明确“大胸显小”'],
  '3741912387062727047':['小胸','轻氧、细肩带、无痕日常定位，未出现大胸专属词，按小胸倾向'],
  '3826430147087696355':['小胸','隐形、细闪肩带、日常轻薄定位，未出现大胸专属词，按小胸倾向'],
  '3627758904315881666':['大胸','详情含防外扩/收副乳，且为软支撑承托定位，按大胸倾向'],
  '3679328215173825003':['大胸','详情含承托/收副乳/防外扩，按大胸支撑定位'],
  '3756389714454774277':['大胸','标题明确“大胸显小”'],
  '3826919824940990563':['大胸','详情含调整型/提拉/收副乳，且适合下垂胸型，按大胸倾向；用户复核不按抹胸'],
  '3553455477876749412':['大胸','四排搭扣、防滑、蹦跳不掉，强调无肩带承托，按大胸倾向'],
  '3501764008359424019':['大胸','标题明确“大胸显小”'],
  '3829082899337052239':['小胸','深V聚拢/蕾丝无钢圈卖点，未出现大胸专属词，按小胸倾向'],
  '3745969039508373790':['小胸','标题明确“小胸”'],
  '3661193526777093841':['小胸','心动杯/3⁄4杯聚拢定位，未出现大胸专属词，按小胸倾向'],
  '3797750243215409473':['小胸','详情标注发育期少女/少女文胸，按小胸成长阶段定位'],
  '3572382409028680808':['大胸','标题与详情明确“大胸显小”，并含调整/塑形/收副乳'],
  '3772705322511237455':['大胸','标题与详情明确大胸显瘦/大胸显小'],
  '3737785318527598964':['大胸','标题与详情明确“大胸显小”'],
  '3830713097065202162':['小胸','标题明确“小胸聚拢”'],
};

// Build unique products with one primary selling-point category and one size bucket.
const products=[];
for(const [id,info] of sourceRows.entries()){
  const row=[...info.row];
  const tags=collectTags(id);
  const primary=primaryFor(id,tags);
  const [size,reason]=sizeMap[id]||['小胸','未出现明确尺寸词；按商品轻薄/支撑卖点作倾向判断'];
  const evidenceParts=[];
  for(const x of sourceCats.get(id)||[]){
    for(const seg of String(x.row[18]??'').split('；').filter(Boolean)){
      if(id==='3826919824940990563' && seg.startsWith('抹胸：')) continue;
      if(!evidenceParts.includes(seg)) evidenceParts.push(seg);
    }
  }
  row[18]=evidenceParts.join('；');
  row[19]=tags.join('、');
  row[23]=`主卖点：${primary}；胸型：${size}；按原榜排名排序${id==='3826919824940990563'?'；用户复核：实物不按抹胸':' '}`.trim();
  products.push({id,row,primary,size,reason,sourceSheet:info.sheet,sourceCats:[...new Set((sourceCats.get(id)||[]).map(x=>x.sheet))],rank:Number(row[4]),url:String(row[10]??''),tags});
}
products.sort((a,b)=>a.rank-b.rank || a.id.localeCompare(b.id));

// Create new disjoint category-size sheets from the existing daily style, then remove the old duplicated category sheets.
const newNames=[];
const keyToName=(cat,size)=>`${cat}（${size}）TOP10`;
const asciiKey=(cat,size)=>({日常:'Daily',抹胸:'Bustier',前扣:'FrontClose',束背:'BackSupport',矫正:'Corrective',聚拢:'Gathering'}[cat]+(size==='大胸'?'Big':'Small')+'Top10Table');
for(const cat of ['日常','抹胸','前扣','束背','矫正','聚拢']){
  for(const size of ['大胸','小胸']){
    const name=keyToName(cat,size); newNames.push(name);
    const sh=wb.worksheets.add(name);
    // Match the original table style/layout before writing new disjoint data.
    sh.getRange('A1:X11').copyFrom(templateRange,'all');
    sh.getRange('A1:AC60').clear({applyTo:'contents'});
    const header=[...templateRange.values[0].slice(0,24), '主卖点分类','胸型判定','胸型判断依据','分类复核说明','商品链接URL'];
    header[19]='原始命中标签';
    header[23]='复核结论';
    sh.getRange('A1:AC1').values=[header];
    const rows=products.filter(p=>p.primary===cat && p.size===size).slice(0,10);
    if(rows.length){
      const body=rows.map(p=>{
        const r=[...p.row];
        // Keep the raw URL in AC and make K a real Excel hyperlink formula with a visible fallback for renderer compatibility.
        r[10]=null;
        return [...r,p.primary,p.size,p.reason,(p.id==='3826919824940990563'?'用户复核：标题虽含“抹胸”，按实物不列入抹胸；归入聚拢/提拉':'单一主卖点归类，避免与其他分类重复'),p.url];
      });
      sh.getRange(`A2:AC${rows.length+1}`).values=body;
      sh.getRange(`K2:K${rows.length+1}`).formulas=rows.map((p,i)=>{const rr=i+2; return [`=IFERROR(HYPERLINK(AC${rr},"打开链接"),AC${rr})`];});
      sh.getRange(`X2:X${rows.length+1}`).values=rows.map(p=>[p.row[23]]);
    }
    const table=sh.tables.add(`A1:AC${Math.max(1,rows.length+1)}`,true,asciiKey(cat,size));
    table.style='TableStyleMedium2';
    sh.freezePanes.freezeRows(1);
    sh.getRange('A1:AC60').format.wrapText=true;
    sh.getRange('K1:K60').format.font={color:'#0563C1'};
    sh.getRange('Y1:Y60').format.font={bold:false};
    sh.getRange('AA1:AB60').format.wrapText=true;
    sh.getRange('AC1:AC60').format.wrapText=true;
    // Keep original widths for A:X, add readable widths for audit fields.
    for(const [col,w] of [['A',16],['B',12],['C',34],['D',14],['E',8],['F',10],['G',48],['H',22],['I',8],['J',52],['K',20],['L',16],['M',18],['N',22],['O',16],['P',14],['Q',14],['R',16],['S',42],['T',22],['U',14],['V',54],['W',14],['X',42],['Y',14],['Z',12],['AA',50],['AB',52],['AC',48]]) sh.getRange(`${col}1:${col}60`).format.columnWidth=w;
    sh.getRange('A1:AC1').format.rowHeight=30;
    if(rows.length) sh.getRange(`A2:AC${rows.length+1}`).format.rowHeight=48;
  }
}
for(const name of oldCategorySheets) wb.worksheets.getItem(name).delete();

// Make product-link columns directly clickable in the raw and non-bra category sheets too.
// Use the remaining sheets directly; the long raw-sheet name varies by punctuation.
for(const sh of wb.worksheets.items){
  const name=String(sh.name??'');
  if(newNames.includes(name) || name==='分类说明') continue;
  const used=sh.getUsedRange();
  if(!used || !used.values?.length || used.values[0].length<11) continue;
  const vals=used.values;
  const last=vals.length;
  const urls=[];
  for(let r=1;r<last;r++) urls.push([String(vals[r][10]??'')]);
  const extraCol=String.fromCharCode(65+used.values[0].length); // S for A:R sheets
  sh.getRange(`${extraCol}1`).values=[['商品链接URL']];
  if(urls.length){
    sh.getRange(`${extraCol}2:${extraCol}${last}`).values=urls;
    sh.getRange(`K2:K${last}`).formulas=urls.map((_,i)=>{const rr=i+2; return [`=IFERROR(HYPERLINK(${extraCol}${rr},"打开链接"),${extraCol}${rr})`];});
  }
  sh.getRange(`${extraCol}1:${extraCol}${last}`).format.wrapText=true;
  sh.getRange(`${extraCol}1:${extraCol}${last}`).format.columnWidth=48;
  sh.getRange(`K1:K${last}`).format.font={color:'#0563C1'};
}

// Add an auditable explanation and counts sheet.
const note=wb.worksheets.add('分类说明');
const counts={};
for(const cat of ['日常','抹胸','前扣','束背','矫正','聚拢']){ counts[cat]={大胸:products.filter(p=>p.primary===cat&&p.size==='大胸').length,小胸:products.filter(p=>p.primary===cat&&p.size==='小胸').length}; }
const noteRows=[
 ['项目','规则/结果'],
 ['分类方式','每个商品只进入一个主卖点榜单，避免同一商品在日常、抹胸、前扣、束背、矫正、聚拢之间重复。'],
 ['主卖点优先级','矫正 > 前扣 > 抹胸 > 束背 > 聚拢 > 日常；前扣按闭合结构优先，日常仅保留没有更强结构/功能卖点的商品。'],
 ['用户复核例外','“【挚爱系列】时尚百搭提拉夏季抹胸细闪透气外穿文胸”按实物复核移出抹胸；本文件中的婷美DT9仍依据详情明确的“款式：抹胸款”保留抹胸。'],
 ['胸型判定','明确出现“大胸显小/大胸显瘦/大胸/下垂/收副乳/防外扩/调整承托”等，判为大胸；明确出现“小胸”或“发育期少女”，判为小胸；没有尺寸词的商品按支撑型或轻薄型卖点作倾向判断，依据写在各表“胸型判断依据”。'],
 ['排序','各榜按原始榜单“排名”升序，最多保留前10条；未估算销量。'],
 ['链接','各表K列为Excel可点击公式；AC列（原始输出表）或S列（原始/内裤/塑身衣表）保留商品链接URL。'],
 ['商品总数',products.length],
];
for(const cat of ['日常','抹胸','前扣','束背','矫正','聚拢']){
  noteRows.push([`${cat}（大胸）`,counts[cat].大胸]);
  noteRows.push([`${cat}（小胸）`,counts[cat].小胸]);
}
note.getRange(`A1:B${noteRows.length}`).values=noteRows;
note.getRange('A1:B1').format={fill:'#D9EAF7',font:{bold:true,color:'#000000'}};
note.getRange(`A1:B${noteRows.length}`).format.wrapText=true;
note.getRange('A1:A20').format.columnWidth=18;
note.getRange('B1:B20').format.columnWidth=110;
note.getRange(`A2:B${noteRows.length}`).format.rowHeight=38;
note.getRange('A1:B1').format.rowHeight=26;
note.freezePanes.freezeRows(1);

// Compact audit checks before export.
for(const name of newNames){
  const sh=wb.worksheets.getItem(name); const vals=sh.getUsedRange().values;
  const ranks=[]; const ids=[];
  for(let i=1;i<vals.length;i++){ if(vals[i][6]){ranks.push(Number(vals[i][4])); ids.push(String(vals[i][7]));} }
  if(!ranks.every((x,i)=>i===0||x>=ranks[i-1])) throw new Error(`排序失败: ${name}`);
  if(new Set(ids).size!==ids.length) throw new Error(`重复商品: ${name}`);
}
const countsById=new Map();
for(const name of newNames){const vals=wb.worksheets.getItem(name).getUsedRange().values; for(let i=1;i<vals.length;i++) if(vals[i][7]) countsById.set(String(vals[i][7]),(countsById.get(String(vals[i][7]))||0)+1);}
for(const [id,n] of countsById) if(n!==1) throw new Error(`跨表重复: ${id} x${n}`);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A',options:{useRegex:true,maxResults:300},summary:'final formula error scan'});
console.log('ERRORS',errors.ndjson);
console.log('PRODUCTS',JSON.stringify(products.map(p=>({id:p.id,rank:p.rank,primary:p.primary,size:p.size,title:p.row[6]}))));
console.log('COUNTS',JSON.stringify(counts));
const previewNames=['日常（大胸）TOP10','日常（小胸）TOP10','抹胸（大胸）TOP10','聚拢（大胸）TOP10','分类说明'];
for(const n of previewNames){ const blob=await wb.render({sheetName:n,autoCrop:'all',scale:1,format:'png'}); await fs.writeFile(`${outputDir}/${n}_预览.png`,new Uint8Array(await blob.arrayBuffer())); }
const check=await wb.inspect({kind:'table',sheetId:'抹胸（大胸）TOP10',range:'A1:AC8',include:'values,formulas',tableMaxRows:8,tableMaxCols:29,maxChars:16000});
console.log('CHECK',check.ndjson);
const out=await SpreadsheetFile.exportXlsx(wb); await out.save(outputPath); console.log(`OUTPUT=${outputPath}`);
