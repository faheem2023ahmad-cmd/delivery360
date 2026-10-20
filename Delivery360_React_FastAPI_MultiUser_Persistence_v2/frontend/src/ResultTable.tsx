import {Children,cloneElement,isValidElement,useState} from 'react';
import type {ComponentProps,ReactElement,ReactNode} from 'react';
import type {Element, Root} from 'hast';

function textContent(node: Element): string {
 return node.children.map(child => child.type === 'text' ? child.value : child.type === 'element' ? textContent(child) : '').join('');
}

// Keep metadata local to each table, including responses containing multiple tables.
export function tableMetadata() {
 return (tree: Root) => {
  function visit(parent: Root | Element) {
   for(let i=0;i<parent.children.length;i++) {
    const node=parent.children[i];
    if(node.type!=='element')continue;
    if(node.tagName!=='table'){visit(node);continue;}
    const preceding: {index:number,node:Element}[]=[];
    for(let j=i-1;j>=0;j--){
     const sibling=parent.children[j];
     if(sibling.type==='text'&&!sibling.value.trim())continue;
     if(sibling.type!=='element')break;
     preceding.unshift({index:j,node:sibling});
     if(preceding.length===2)break;
    }
    const heading=preceding.find(item=>/^h[1-6]$/.test(item.node.tagName));
    const paragraph=preceding.find(item=>item.node.tagName==='p'&&item.index===(preceding[preceding.length-1]?.index));
    const head=node.children.find(child=>child.type==='element'&&child.tagName==='thead');
    const labels=head?.type==='element'?head.children.flatMap(row=>row.type==='element'?row.children.filter(cell=>cell.type==='element').map(cell=>textContent(cell as Element)):[]):[];
    node.properties.cardTitle=heading?textContent(heading.node):labels.join(' / ')||'Results';
    node.properties.cardContext=paragraph?textContent(paragraph.node):'';
    // Move only immediately associated headings/context into the card.
    const consumed=[heading,paragraph].filter((item):item is {index:number,node:Element}=>!!item);
    for(const item of consumed.sort((a,b)=>b.index-a.index)){
     parent.children.splice(item.index,1);i--;
    }
   }
  }
  visit(tree);
 };
}

type ChildElement=ReactElement<{children?:ReactNode}>;
function elements(children:ReactNode):ChildElement[]{return Children.toArray(children).filter(isValidElement) as ChildElement[];}
export function compareCells(a:string,b:string):number {
 const numeric=(value:string)=>/^[+-]?(?:\d[\d,]*\.?\d*|\.\d+)\s*%?$/.test(value.trim())?Number(value.replace(/[, %]/g,'')):null;
 const x=numeric(a),y=numeric(b);
 return x!==null&&y!==null?x-y:a.localeCompare(b,undefined,{numeric:true,sensitivity:'base'});
}
export function csvText(rows:string[][]):string {
 return '\uFEFF'+rows.map(row=>row.map(value=>{
  // Keep spreadsheet formulas as literal text when opening the export in Excel.
  const safe=/^[\s]*[=+@-]/.test(value)?"'"+value:value;
  return '"'+safe.replace(/"/g,'""')+'"';
 }).join(',')).join('\r\n');
}
export function ResultTable({node,children,...props}:ComponentProps<'table'> & {node?:Element}) {
 const [filter,setFilter]=useState(''),[sort,setSort]=useState<{column:number,direction:number}|null>(null);
 const title=String(node?.properties.cardTitle||'Results');
 const context=String(node?.properties.cardContext||'');
 const head=node?.children.find(child=>child.type==='element'&&child.tagName==='thead');
 const body=node?.children.find(child=>child.type==='element'&&child.tagName==='tbody');
 const astRows=(section:typeof head)=>section?.type==='element'?section.children.filter((child):child is Element=>child.type==='element'&&child.tagName==='tr'):[];
 const values=(row:Element)=>row.children.filter((child):child is Element=>child.type==='element').map(textContent);
 const headers=astRows(head).flatMap(values);
 const rows=astRows(body).map((row,index)=>({index,values:values(row)}));
 const query=filter.trim().toLocaleLowerCase();
 const visible=rows.filter(row=>row.values.some(value=>value.toLocaleLowerCase().includes(query)));
 if(sort)visible.sort((a,b)=>sort.direction*compareCells(a.values[sort.column]||'',b.values[sort.column]||'')||a.index-b.index);
 const sections=elements(children),renderedHead=sections.find(section=>section.type==='thead'),renderedBody=sections.find(section=>section.type==='tbody');
 const renderedRows=elements(renderedBody?.props.children);
 const cleanProps={...props} as Record<string,unknown>;
 delete cleanProps.cardTitle;delete cleanProps.cardContext;
 function download(){
  const url=URL.createObjectURL(new Blob([csvText([headers,...visible.map(row=>row.values)])],{type:'text/csv;charset=utf-8;'}));
  const link=document.createElement('a');link.href=url;link.download=(title.replace(/[^a-z0-9]+/gi,'-').replace(/^-|-$/g,'').slice(0,80)||'results')+'.csv';
  document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 return <section className="table-card" aria-label={title}>
  <div className="table-card-heading"><div><h3>{title}</h3>{context&&<p>{context}</p>}</div><span className="table-count" aria-live="polite">{visible.length} of {rows.length} rows shown</span></div>
  <div className="table-tools"><label>Filter rows<input type="search" value={filter} onChange={event=>setFilter(event.target.value)} placeholder="Search all columns"/></label>{filter&&<button type="button" onClick={()=>setFilter('')}>Clear filter</button>}{sort&&<button type="button" onClick={()=>setSort(null)}>Reset sorting</button>}<button type="button" onClick={download}>Download CSV</button></div>
  <div className="result-table" role="region" aria-label={title} tabIndex={0}><table {...cleanProps}>
   <thead>{elements(renderedHead?.props.children).map((row,rowIndex)=>cloneElement(row,{key:rowIndex},elements(row.props.children).map((cell,column)=><th key={column} aria-sort={sort?.column===column?(sort.direction===1?'ascending':'descending'):'none'}><button type="button" className="sort-column" onClick={()=>setSort({column,direction:sort?.column===column?-sort.direction:1})}>{cell.props.children}<span aria-hidden="true">{sort?.column===column?(sort.direction===1?' ?':' ?'):' ?'}</span></button></th>)))}</thead>
   <tbody>{visible.map(row=>renderedRows[row.index]&&cloneElement(renderedRows[row.index],{key:row.index}))}{!visible.length&&<tr><td colSpan={Math.max(headers.length,1)}>No matching rows.</td></tr>}</tbody>
  </table></div>
 </section>;
}
