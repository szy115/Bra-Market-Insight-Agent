import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const base = String.raw`C:\Users\HSIA\Documents\Insight Agent\outputs\bra_product_classification_20260731\文胸商品_多标签TOP10_售价120以上_2026-07_修正版.xlsx`;
const out = String.raw`C:\Users\HSIA\Documents\Insight Agent\outputs\bra_product_classification_20260731\文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx`;
const braWb = await SpreadsheetFile.importXlsx(await FileBlob.load(base));
const topSheets = ['日常TOP10','抹胸TOP10','前扣TOP10','束背TOP10','矫正TOP10','聚拢TOP10','运动TOP10'];
function rankVal(v){ const n=Number(v); return Number.isFinite(n)?n:999999; }
function normalizeRows(rows, limit=10){
  const header = rows[0].slice();
  const estIdx = header.indexOf('销量估算（件）');
  const body = rows.slice(1).filter(r=>r.some(v=>v!==null && v!==''));
  body.sort((a,b)=>rankVal(a[4])-rankVal(b[4]));
  const selected = body.slice(0,limit).map(r=> estIdx>=0 ? r.filter((_,i)=>i!==estIdx) : r.slice());
  const h = estIdx>=0 ? header.filter((_,i)=>i!==estIdx) : header;
  return [h,...selected];
}
for (const sn of topSheets){
  const ws=braWb.worksheets.getItem(sn); const vals=ws.getUsedRange().values; const outRows=normalizeRows(vals,10);
  ws.getRange('A1:Z40').clear({applyTo:'contents'});
  ws.getRangeByIndexes(0,0,outRows.length,outRows[0].length).values=outRows;
  ws.getRange('A1:W1').format.wrapText=true;
}
for (const [srcPath, sn] of [
  [String.raw`C:\Users\HSIA\Downloads\女士内裤.xlsx`,'女士内裤TOP10'],
  [String.raw`C:\Users\HSIA\Downloads\塑身衣.xlsx`,'塑身衣TOP10']
]){
  const srcWb=await SpreadsheetFile.importXlsx(await FileBlob.load(srcPath));
  const srcWs=srcWb.worksheets.getItemAt(0); const vals=srcWs.getUsedRange().values; const outRows=normalizeRows(vals,10);
  let ws;
  try { ws=braWb.worksheets.getItem(sn); ws.getRange('A1:Z40').clear({applyTo:'all'}); }
  catch { ws=braWb.worksheets.add(sn); }
  ws.getRangeByIndexes(0,0,outRows.length,outRows[0].length).values=outRows;
  ws.getRange('A1:R1').format.wrapText=true;
  ws.freezePanes.freezeRows(1);
}
const mapSheet=braWb.worksheets.getItem('销量区间映射'); mapSheet.getRange('A1:B20').clear({applyTo:'contents'}); mapSheet.getRange('A1:B2').values=[['本版不使用销量估算',''],['各分类页按原始总榜排名升序取前十','']];
const note=braWb.worksheets.getItem('筛选说明');
note.getRange('A10:F14').clear({applyTo:'contents'});
note.getRange('A10:F14').values=[
 ['本版排名口径说明','','','','',''],
 ['各分类页均按原始总榜“排名”升序取前10，不再估算销量。','','','','',''],
 ['原“排名”列保留，表示平台原始总榜排名；各分类页仅展示该类目对应的前十商品。','','','','',''],
 ['新增分类页：女士内裤TOP10、塑身衣TOP10。','','','','',''],
 ['文胸分类页继续按售价下限≥120元筛选；内裤、塑身衣页沿用各自原始表数据。','','','','','']
];
await fs.mkdir(String.raw`C:\Users\HSIA\Documents\Insight Agent\outputs\bra_product_classification_20260731`,{recursive:true});
const blob=await SpreadsheetFile.exportXlsx(braWb); await blob.save(out);
console.log(out);


