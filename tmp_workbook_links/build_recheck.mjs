import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const inputPath='C:/Users/HSIA/Desktop/任务/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx';
const outputDir='C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1';
const outputPath=`${outputDir}/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07_复核版.xlsx`;
await fs.mkdir(outputDir,{recursive:true});
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));

const categorySheets=['日常TOP10','抹胸TOP10','前扣TOP10','束背TOP10','矫正TOP10','聚拢TOP10'];
const changes=[];
const integrity=[];
const keepForBack=[];

function revise(row){
  const product=String(row[6]??'');
  const evidence=String(row[18]??'');
  const summary=String(row[21]??'');
  const original=String(row[19]??'');
  let tags=original?original.split('、').filter(Boolean):[];
  const removed=[];
  if(tags.includes('运动')){
    // "运动风" or a generic支撑字段 is not enough; retain only explicit sports products.
    const explicitSport=/(运动内衣|运动文胸|瑜伽|健身|跑步|训练)/.test(product);
    if(!explicitSport){ tags=tags.filter(t=>t!=='运动'); removed.push('运动（运动风/支撑字段不等于运动内衣）'); }
  }
  if(tags.includes('束背')){
    const seg=evidence.split('；').find(x=>x.startsWith('束背：'))||'';
    const backText=seg.slice(3);
    const explicitBack=/(束背|背心式|背心款|背部支撑|塑形)/.test(backText+' '+summary);
    if(!explicitBack){ tags=tags.filter(t=>t!=='束背'); removed.push('束背（仅美背/露背，不足以证明束背支撑）'); }
  }
  const revised=tags.join('、');
  const evidenceParts=evidence.split('；').filter(Boolean).filter(x=>{
    if(x.startsWith('运动：') && removed.some(r=>r.startsWith('运动'))) return false;
    if(x.startsWith('束背：') && removed.some(r=>r.startsWith('束背'))) return false;
    return true;
  });
  return {product,original,revised,evidence:evidenceParts.join('；'),removed};
}

for(const name of categorySheets){
  const sheet=wb.worksheets.getItem(name);
  const vals=sheet.getUsedRange().values;
  const oldData=[];
  const notes=[];
  let count=0;
  const ranks=[];
  for(let r=1;r<vals.length;r++){
    if(!vals[r][6]) continue;
    const rev=revise(vals[r]);
    const excelRow=r+1;
    if(rev.removed.length){
      sheet.getRange(`S${excelRow}:T${excelRow}`).values=[[rev.evidence,rev.revised]];
      changes.push({sheet:name,row:excelRow,rank:vals[r][4],product:rev.product,original:rev.original,revised:rev.revised,reason:rev.removed.join('；')});
    }
    const note=rev.removed.length?`修正后：${rev.revised||'无命中标签'}；${rev.removed.join('；')}`:`通过：${rev.revised}`;
    notes.push([note]);
    count++; ranks.push(Number(vals[r][4]));
    oldData.push({row:vals[r],rev});
  }
  // X is the existing blank table column; use it for an auditable review conclusion.
  sheet.getRange('X1').values=[['复核结论']];
  let compact=oldData;
  if(name==='束背TOP10'){
    compact=oldData.filter(x=>x.rev.revised.split('、').includes('束背'));
    keepForBack.push(...compact.map(x=>x.row[4]));
    const table=sheet.tables.items[0];
    if(table) table.delete();
    sheet.getRange(`A1:X${Math.max(vals.length,compact.length+1)}`).clear({applyTo:'contents'});
    sheet.getRange('A1:W1').values=[vals[0].slice(0,23)];
    sheet.getRange('X1').values=[['复核结论']];
    if(compact.length){
      sheet.getRange(`A2:W${compact.length+1}`).values=compact.map(x=>x.row.slice(0,23));
      sheet.getRange(`S2:T${compact.length+1}`).values=compact.map(x=>[x.rev.evidence,x.rev.revised]);
      sheet.getRange(`X2:X${compact.length+1}`).values=compact.map(x=>[`通过：${x.rev.revised}`]);
    }
    const newTable=sheet.tables.add(`A1:X${compact.length+1}`,true,'束背Top10Table');
    newTable.style='TableStyleMedium2';
    integrity.push({sheet:name,count:compact.length,sorted:compact.every((x,i)=>i===0||Number(x.row[4])>=Number(compact[i-1].row[4])),note:'仅保留复核后仍命中束背的商品'});
  }else{
    sheet.getRange(`X2:X${vals.length}`).values=notes;
    integrity.push({sheet:name,count,sorted:ranks.every((x,i)=>i===0||x>=ranks[i-1]),unique:new Set(ranks).size===ranks.length});
  }
}

// Add a compact audit sheet so the changed rule and each correction are visible.
const audit=wb.worksheets.getOrAdd('复核记录',{renameFirstIfOnlyNewSpreadsheet:false});
audit.getRange('A1:F1').values=[['复核项目','复核结论','说明','原标签','复核后标签','涉及商品/范围']];
const rows=[
  ['标签规则','已更新','运动仅接受商品明确为运动内衣/运动文胸/瑜伽/健身/跑步/训练；“运动风”或“运动支撑强度”不单独算运动','','','全部文胸分类表'],
  ['标签规则','已更新','束背需有束背/背心式/背心款/背部支撑/塑形证据；仅“美背/露背”不单独算束背','','','全部文胸分类表'],
  ['排名顺序','通过','各分类表按原榜排名升序，未重排销量或排名','','','日常/抹胸/前扣/束背/矫正/聚拢/内裤/塑身衣'],
  ['内裤、塑身衣','通过','保留原始类目榜单和好货链接，未将其强行套用文胸标签','','','女士内裤TOP10、塑身衣TOP10'],
];
for(const c of changes) rows.push(['商品标签修正','已修正',c.reason,c.original,c.revised,`${c.sheet} 第${c.row}行｜原榜排名${c.rank}｜${c.product}`]);
audit.getRange(`A2:F${rows.length+1}`).values=rows;
audit.getRange('A1:F1').format={fill:'#D9EAF7',font:{bold:true,color:'#000000'}};
audit.getRange(`A1:F${rows.length+1}`).format.wrapText=true;
audit.getRange('A1:F1').format.rowHeight=24;
audit.getRange(`A2:F${rows.length+1}`).format.rowHeight=36;
for(const [col,w] of [['A',18],['B',14],['C',58],['D',26],['E',24],['F',68]]) audit.getRange(`${col}:${col}`).format.columnWidth=w;
audit.freezePanes.freezeRows(1);

const check=await wb.inspect({kind:'table',sheetId:'束背TOP10',range:'A1:X12',include:'values,formulas',tableMaxRows:12,tableMaxCols:24,maxChars:12000});
console.log(check.ndjson);
console.log(JSON.stringify({changes,integrity,keepForBack}));
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A',options:{useRegex:true,maxResults:200},summary:'final formula error scan'});
console.log(errors.ndjson);
const preview1=await wb.render({sheetName:'束背TOP10',range:'A1:X10',scale:1,format:'png'});
await fs.writeFile(`${outputDir}/束背TOP10_复核预览.png`,new Uint8Array(await preview1.arrayBuffer()));
const preview2=await wb.render({sheetName:'复核记录',range:`A1:F${Math.min(rows.length+1,20)}`,scale:1,format:'png'});
await fs.writeFile(`${outputDir}/复核记录_预览.png`,new Uint8Array(await preview2.arrayBuffer()));
const out=await SpreadsheetFile.exportXlsx(wb);
await out.save(outputPath);
console.log(`OUTPUT=${outputPath}`);
