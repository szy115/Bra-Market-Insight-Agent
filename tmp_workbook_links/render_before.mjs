import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load('C:/Users/HSIA/Downloads/抖音大盘2026年上半年销量前100商品（文胸、运动内衣、贴合内衣、光腿神器）.xlsx'));
const outDir='C:/Users/HSIA/Documents/Insight Agent/tmp_workbook_links';
for (const name of ['贴合内衣','文胸']) {
  const p=await wb.render({sheetName:name,range:name==='贴合内衣'?'A1:D12':'A1:F8',scale:1,format:'png'});
  await fs.writeFile(`${outDir}/${name}_before.png`,new Uint8Array(await p.arrayBuffer()));
}
