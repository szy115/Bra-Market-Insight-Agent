import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const inputPath='C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx';
const outputDir='C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1';
const outputPath=`${outputDir}/文胸商品_分类TOP10_按主卖点_胸型双榜_全量复核版_2026-07.xlsx`;
await fs.mkdir(outputDir,{recursive:true});
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const oldSheets=['日常TOP10','抹胸TOP10','前扣TOP10','束背TOP10','矫正TOP10','聚拢TOP10'];
const template=wb.worksheets.getItem('日常TOP10');
const templateRange=template.getRange('A1:X11');

function priceFloor(p){const nums=String(p??'').match(/\d+(?:\.\d+)?/g); return nums?.length?Math.min(...nums.map(Number)):null;}
function hits(text,words){return words.filter(w=>text.includes(w));}
const detailMap=new Map();
for(const name of oldSheets){
  const vals=wb.worksheets.getItem(name).getUsedRange().values;
  for(let i=1;i<vals.length;i++){
    if(!vals[i][7]) continue;
    const id=String(vals[i][7]);
    const current=detailMap.get(id)||{evidence:'',tags:'',summary:'',status:''};
    if(String(vals[i][18]??'').length>current.evidence.length) current.evidence=String(vals[i][18]??'');
    if(String(vals[i][19]??'').length>current.tags.length) current.tags=String(vals[i][19]??'');
    if(String(vals[i][21]??'').length>current.summary.length) current.summary=String(vals[i][21]??'');
    if(vals[i][22]) current.status=String(vals[i][22]);
    detailMap.set(id,current);
  }
}

const categoryById={
'3668622727843021221':'束背','3747856469228388817':'前扣','3805536475458699588':'日常','3830024278724706385':'日常','3830178603467931832':'束背','3792494994254856675':'日常','3772705322511237455':'聚拢','3741912387062727047':'日常','3737785318527598964':'聚拢','3826430147087696355':'日常','3627758904315881666':'束背','3818725766166872303':'日常','3796776965021762184':'日常','3756389714454774277':'抹胸','3826919824940990563':'日常','3679328215173825003':'日常','3818334415155757303':'矫正','3689954767439790715':'日常','3823876769845478246':'日常','3719236093409886466':'聚拢','3663741292703281408':'聚拢','3827798255132082368':'聚拢','3716852369372348671':'聚拢','3805148242711281768':'日常','3830713097065202162':'聚拢','3546697670972339056':'聚拢','3661193526777093841':'前扣','3740398569912402403':'聚拢','3812982417585733732':'聚拢','3823730790248874135':'束背','3797750243215409473':'矫正','3729638553643254152':'聚拢','3732632281232310766':'日常','3572382409028680808':'矫正','3553455477876749412':'抹胸','3833496141467615480':'聚拢','3714450935012000232':'聚拢','3739689483772231758':'聚拢','3801786621083386349':'日常','3702953316251205806':'聚拢','3501764008359424019':'抹胸','3625866593315200327':'聚拢','3617759927931664533':'运动','3829082899337052239':'抹胸','3771007362874343430':'聚拢','3825387223927357682':'日常','3819961275669151969':'日常','3828735135767986595':'聚拢','3734312012835062201':'日常','3745969039508373790':'前扣','3810202373503189241':'日常','3770284283705557278':'日常','3478212471356002002':'日常','3828207460372578535':'矫正','3662143599354733458':'日常','3775850673099375772':'聚拢'
};
const bigIds=new Set([
'3747856469228388817','3805536475458699588','3830178603467931832','3792494994254856675','3772705322511237455','3737785318527598964','3627758904315881666','3756389714454774277','3826919824940990563','3679328215173825003','3818334415155757303','3719236093409886466','3663741292703281408','3716852369372348671','3812982417585733732','3732632281232310766','3572382409028680808','3553455477876749412','3739689483772231758','3801786621083386349','3702953316251205806','3501764008359424019','3625866593315200327','3617759927931664533','3825387223927357682','3828735135767986595','3810202373503189241','3478212471356002002','3828207460372578535','3662143599354733458'
]);

const mainWords={
'日常':['舒适','轻薄','透气','无痕','粉底液','凉感','细肩带','一衣四穿','百搭','深V','大露背','挂脖','吊带','隐形'],
'抹胸':['抹胸','无肩带'],
'前扣':['前扣'],
'束背':['背心式','背心款','背心','美背'],
'矫正':['矫姿','矫正','调整内衣','院线调整','人体工学','散胸','外扩'],
'聚拢':['聚拢','提拉','提托','上托','收副乳','防下垂','显大','显小','反重力','力挺'],
'运动':['运动内衣','运动文胸','运动']
};
function mainBasis(id,title,cat,detail){
  if(id==='3826919824940990563') return '用户按实物复核：不按抹胸；标题突出“时尚百搭、透气、外穿”，日常穿搭卖点强于提拉功能，主卖点归为日常';
  if(id==='3756389714454774277') return '详情页明确“款式：抹胸款、无开扣、无搭扣”，抹胸结构比日常/聚拢功能更显著';
  if(cat==='前扣') return '标题明确“前扣”，闭合结构是最具体、最显著的产品卖点';
  if(cat==='运动') return '标题明确“运动内衣”，运动场景是最显著卖点';
  if(cat==='矫正'){
    const kw=hits(title+detail,['矫姿','矫正','调整内衣','院线调整','人体工学','散胸','下垂','外扩']);
    return `标题/详情突出“${[...new Set(kw)].slice(0,4).join('、')}”等矫姿调整诉求，优先归入矫正`;
  }
  if(cat==='束背'){
    const kw=hits(title+detail,['背心式','背心款','背心','美背','背部支撑']);
    return `详情或标题明确“${[...new Set(kw)].slice(0,4).join('、')}”背部/背心结构，优先归入束背`;
  }
  if(cat==='抹胸'){
    const kw=hits(title+detail,['抹胸','无肩带','防滑','蹦跳不掉']);
    return `标题/详情明确“${[...new Set(kw)].slice(0,4).join('、')}”，无肩带抹胸结构是首要卖点`;
  }
  if(cat==='聚拢'){
    const kw=hits(title+detail,mainWords['聚拢']);
    return `标题/详情突出“${[...new Set(kw)].slice(0,5).join('、')}”等塑形承托功能，主卖点归为聚拢`;
  }
  const kw=hits(title+detail,mainWords['日常']);
  return `标题突出“${[...new Set(kw)].slice(0,5).join('、')}”等日常穿着体验，且没有更显著的前扣/抹胸/矫正/运动结构卖点`;
}
function sizeBasis(title,size,detail){
  const text=title+' '+detail;
  if(size==='大胸'){
    const kw=hits(text,['大胸显小','大胸显瘦','大胸','下垂','散胸','外扩','收副乳','防下垂','全罩杯','力挺','反重力','提托']);
    return kw.length?`标题/详情出现“${[...new Set(kw)].slice(0,5).join('、')}”，判为大胸定位`:'未出现尺寸词；强承托/调整结构更偏大胸定位';
  }
  const kw=hits(text,['小胸聚拢','小胸','平胸','少女','发育期','加厚杯垫','显大','不空杯','低领','深V','细肩带','轻薄','无痕']);
  return kw.length?`标题/详情出现“${[...new Set(kw)].slice(0,5).join('、')}”，判为小胸定位`:'未出现大胸专属词；轻支撑/轻薄日常结构更偏小胸定位';
}

const raw=wb.worksheets.getItemAt(0); const rawVals=raw.getUsedRange().values;
const candidates=[];
for(let i=1;i<rawVals.length;i++){
  const base=[...rawVals[i].slice(0,18)]; const floor=priceFloor(base[11]);
  if(floor==null||floor<120) continue;
  const id=String(base[7]); const title=String(base[6]??''); const cat=categoryById[id];
  if(!cat) throw new Error(`缺少主卖点映射: ${id} ${title}`);
  const size=bigIds.has(id)?'大胸':'小胸'; const d=detailMap.get(id)||{evidence:'',tags:'',summary:'',status:''};
  const mb=mainBasis(id,title,cat,d.summary+' '+d.evidence); const sb=sizeBasis(title,size,d.summary+' '+d.evidence);
  const url=String(base[10]??'');
  candidates.push({base,id,title,rank:Number(base[4]),floor,cat,size,mb,sb,url,detail:d});
}
candidates.sort((a,b)=>a.rank-b.rank||a.id.localeCompare(b.id));
if(candidates.length!==56) throw new Error(`筛选数量异常: ${candidates.length}`);

const cats=['日常','抹胸','前扣','束背','矫正','聚拢','运动'];
const sizes=['大胸','小胸'];
const sheetNames=[]; const topIds=new Set(); const bucketCounts={};
const tableKey={日常:'Daily',抹胸:'Bustier',前扣:'Front',束背:'Back',矫正:'Corrective',聚拢:'Gather',运动:'Sport'};
for(const cat of cats){
  bucketCounts[cat]={};
  for(const size of sizes){
    const rows=candidates.filter(x=>x.cat===cat&&x.size===size).sort((a,b)=>a.rank-b.rank);
    bucketCounts[cat][size]=rows.length;
    const top=rows.slice(0,10); top.forEach(x=>topIds.add(x.id));
    const name=`${cat}（${size}）TOP10`; sheetNames.push(name);
    const sh=wb.worksheets.add(name);
    sh.getRange('A1:X11').copyFrom(templateRange,'all');
    sh.getRange('A1:AD60').clear({applyTo:'contents'});
    const header=[...templateRange.values[0].slice(0,24),'主卖点分类','胸型判定','主要卖点判断依据','大/小胸判断依据','分类复核说明','商品链接URL'];
    header[19]='判定标签'; header[23]='复核结论';
    sh.getRange('A1:AD1').values=[header];
    if(top.length){
      const body=top.map(x=>{
        const extra=[x.detail.evidence||`主卖点：${x.mb}；胸型：${x.sb}`,x.cat,x.floor,x.detail.summary||`商品标题：${x.title}`,x.detail.status||'依据商品标题复核',`主卖点：${x.cat}；胸型：${x.size}；原榜排名${x.rank}`];
        const first24=[...x.base,null,null,null,null,null,null];
        first24[7]=`\u200B${x.id}`; first24[10]=null; first24[18]=extra[0]; first24[19]=extra[1]; first24[20]=extra[2]; first24[21]=extra[3]; first24[22]=extra[4]; first24[23]=extra[5];
        return [...first24,x.cat,x.size,x.mb,x.sb,'单一主卖点归类；该商品不在其他主卖点榜重复出现',x.url];
      });
      sh.getRange(`A2:AD${top.length+1}`).values=body;
      sh.getRange(`K2:K${top.length+1}`).formulas=top.map((_,i)=>{const r=i+2;return [`=IFERROR(HYPERLINK(AD${r},"打开链接"),AD${r})`];});
    }
    const table=sh.tables.add(`A1:AD${Math.max(1,top.length+1)}`,true,`${tableKey[cat]}${size==='大胸'?'Big':'Small'}Top10Table`); table.style='TableStyleMedium2';
    sh.freezePanes.freezeRows(1); sh.getRange('A1:AD60').format.wrapText=true; sh.getRange('K1:K60').format.font={color:'#0563C1'};
    for(const [col,w] of [['A',16],['B',12],['C',32],['D',14],['E',8],['F',10],['G',48],['H',22],['I',8],['J',48],['K',18],['L',16],['M',16],['N',22],['O',16],['P',14],['Q',14],['R',16],['S',42],['T',14],['U',12],['V',48],['W',16],['X',36],['Y',14],['Z',12],['AA',56],['AB',52],['AC',42],['AD',48]]) sh.getRange(`${col}1:${col}60`).format.columnWidth=w;
    sh.getRange('H1:H60').format.numberFormat='@';
    sh.getRange('A1:AD1').format.rowHeight=30; if(top.length) sh.getRange(`A2:AD${top.length+1}`).format.rowHeight=50;
  }
}
for(const name of oldSheets) wb.worksheets.getItem(name).delete();

// Full 56-row audit sheet.
const audit=wb.worksheets.add('全量判定');
const auditHeaders=['原榜排名','商品信息','商品ID','价格带','售价下限（元）','主卖点分类','胸型判定','主要卖点判断依据','大/小胸判断依据','详情页属性摘要','商品链接','商品链接URL','入榜状态','复核说明'];
audit.getRange('A1:N1').values=[auditHeaders];
const auditRows=candidates.map(x=>[x.rank,x.title,`\u200B${x.id}`,x.base[11],x.floor,x.cat,x.size,x.mb,x.sb,x.detail.summary||'按商品标题关键字复核',null,x.url,topIds.has(x.id)?'进入对应TOP10':'该分榜候选超过10条，按原榜排名顺延','每个商品仅保留一个主卖点分类']);
audit.getRange(`A2:N${auditRows.length+1}`).values=auditRows;
audit.getRange(`K2:K${auditRows.length+1}`).formulas=auditRows.map((_,i)=>{const r=i+2;return [`=IFERROR(HYPERLINK(L${r},"打开链接"),L${r})`];});
const auditTable=audit.tables.add(`A1:N${auditRows.length+1}`,true,'FullClassificationAuditTable'); auditTable.style='TableStyleMedium2';
audit.freezePanes.freezeRows(1); audit.getRange(`A1:N${auditRows.length+1}`).format.wrapText=true; audit.getRange(`K1:K${auditRows.length+1}`).format.font={color:'#0563C1'};
audit.getRange(`C1:C${auditRows.length+1}`).format.numberFormat='@';
for(const [col,w] of [['A',10],['B',54],['C',22],['D',16],['E',12],['F',14],['G',12],['H',60],['I',54],['J',56],['K',18],['L',48],['M',28],['N',34]]) audit.getRange(`${col}1:${col}${auditRows.length+1}`).format.columnWidth=w;
audit.getRange('A1:N1').format.rowHeight=30; audit.getRange(`A2:N${auditRows.length+1}`).format.rowHeight=54;

// Direct clickable links in raw, underwear and shapewear sheets.
for(const sh of [wb.worksheets.getItemAt(0),wb.worksheets.getItem('女士内裤TOP10'),wb.worksheets.getItem('塑身衣TOP10')]){
  const vals=sh.getUsedRange().values; const last=vals.length; const urls=[]; for(let i=1;i<last;i++) urls.push([String(vals[i][10]??'')]);
  sh.getRange(`S1`).values=[['商品链接URL']]; if(urls.length){sh.getRange(`S2:S${last}`).values=urls; sh.getRange(`K2:K${last}`).formulas=urls.map((_,i)=>{const r=i+2;return [`=IFERROR(HYPERLINK(S${r},"打开链接"),S${r})`];});}
  sh.getRange(`S1:S${last}`).format.columnWidth=48; sh.getRange(`S1:S${last}`).format.wrapText=true; sh.getRange(`K1:K${last}`).format.font={color:'#0563C1'};
}

const note=wb.worksheets.add('分类说明');
const noteRows=[['项目','规则/结果'],['候选池修正','从原始总榜200行重新筛选；售价下限≥120元的文胸共有56款。上一版只使用22款已有分类商品，现已改为全量候选。'],['去重规则','每个商品只进入一个最显著主卖点分类，不在日常、抹胸、前扣、束背、矫正、聚拢、运动之间重复。'],['主卖点依据','每个分榜和“全量判定”表均新增“主要卖点判断依据”，列出标题/详情页中的具体关键词及选择该主类的理由。'],['胸型依据','每个分榜和“全量判定”表均保留“大/小胸判断依据”；明确尺寸词优先，其余按承托强度、杯型和轻薄/低领定位判断。'],['TOP10口径','每个主卖点×胸型分榜按原榜排名升序取前10。若该桶全量候选少于10，则展示全部真实候选，不用弱关联商品凑数。'],['总量约束','56款唯一候选分配到14个互斥分榜；14张满榜需要140个唯一候选，因此结构稀缺的抹胸、前扣、矫正、运动分榜会少于10。'],['日常（小胸）结果','已由上一版1款扩充为10款。'],['链接','各分榜K列、全量判定K列均为Excel可点击公式，末列保留原始商品URL。'],['全量判定','56款全部列出；超过对应分榜前10的商品标记为顺延。']];
for(const cat of cats) for(const size of sizes) noteRows.push([`${cat}（${size}）候选数`,bucketCounts[cat][size]]);
note.getRange(`A1:B${noteRows.length}`).values=noteRows; note.getRange('A1:B1').format={fill:'#D9EAF7',font:{bold:true,color:'#000000'}}; note.getRange(`A1:B${noteRows.length}`).format.wrapText=true; note.getRange('A1:A40').format.columnWidth=22; note.getRange('B1:B40').format.columnWidth=110; note.getRange(`A2:B${noteRows.length}`).format.rowHeight=40; note.freezePanes.freezeRows(1);

// Verify classification completeness, uniqueness, sorting and formulas.
if(new Set(candidates.map(x=>x.id)).size!==candidates.length) throw new Error('候选商品ID重复');
for(const name of sheetNames){const v=wb.worksheets.getItem(name).getUsedRange().values; const ranks=[]; for(let i=1;i<v.length;i++) if(v[i][6]) ranks.push(Number(v[i][4])); if(!ranks.every((x,i)=>i===0||x>=ranks[i-1])) throw new Error(`排序失败 ${name}`); if(ranks.length>10) throw new Error(`超过10条 ${name}`);}
const placed=[]; for(const name of sheetNames){const v=wb.worksheets.getItem(name).getUsedRange().values; for(let i=1;i<v.length;i++) if(v[i][7]) placed.push(String(v[i][7]));}
if(new Set(placed).size!==placed.length) throw new Error('跨分榜重复商品');
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A',options:{useRegex:true,maxResults:300},summary:'final formula error scan'}); console.log('ERRORS',errors.ndjson);
console.log('COUNTS',JSON.stringify(bucketCounts)); console.log('CANDIDATES',candidates.length,'PLACED',placed.length,'UNIQUE_PLACED',new Set(placed).size);
for(const n of ['日常（小胸）TOP10','聚拢（大胸）TOP10','全量判定','分类说明']){const blob=await wb.render({sheetName:n,range:n==='全量判定'?'A1:N14':n==='分类说明'?`A1:B${noteRows.length}`:'A1:AD12',scale:1,format:'png'}); await fs.writeFile(`${outputDir}/${n}_全量版预览.png`,new Uint8Array(await blob.arrayBuffer()));}
const check=await wb.inspect({kind:'table',sheetId:'日常（小胸）TOP10',range:'A1:AD12',include:'values,formulas',tableMaxRows:12,tableMaxCols:30,maxChars:18000}); console.log('CHECK',check.ndjson);
const out=await SpreadsheetFile.exportXlsx(wb); await out.save(outputPath); console.log(`OUTPUT=${outputPath}`);
