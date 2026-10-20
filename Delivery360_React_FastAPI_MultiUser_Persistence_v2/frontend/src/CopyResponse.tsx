import {useEffect,useRef,useState} from 'react';

export function CopyResponse({content}:{content:string}) {
 const [status,setStatus]=useState('');
 const timer=useRef<ReturnType<typeof setTimeout>>();
 useEffect(()=>()=>clearTimeout(timer.current),[]);
 async function copy(){
  try {
   await navigator.clipboard.writeText(content);
   setStatus('Copied');
  } catch {setStatus('Could not copy. Select the response and copy it manually.');}
  clearTimeout(timer.current);timer.current=setTimeout(()=>setStatus(''),4000);
 }
 return <div className="response-actions"><button type="button" onClick={copy}>Copy response</button><span role="status">{status}</span></div>;
}
