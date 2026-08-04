import { Workbook } from '@oai/artifact-tool'; import fs from 'node:fs/promises';
const wb=Workbook.create(); const sh=wb.worksheets.add('T');
sh.getRange('A1:C2').values=[['zws','nbsp','prefix'],['\u200B3830024278724706385','\u00A03830024278724706385','ID:3830024278724706385']]; sh.getRange('A1:C2').format.columnWidth=28;
const b=await wb.render({sheetName:'T',range:'A1:C2',scale:2,format:'png'}); await fs.writeFile('C:/Users/HSIA/Documents/Insight Agent/tmp_workbook_links/idtest2.png',new Uint8Array(await b.arrayBuffer()));
