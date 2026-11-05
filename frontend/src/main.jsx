import React,{useState,useEffect,useRef} from "react";
import{createRoot}from"react-dom/client";
import "./style.css";
import {confirmAction,requestPassword,showAuditDetails,showToast} from "./dialogs";
const API=import.meta.env.DEV?"/api":(import.meta.env.VITE_API_URL||"/api");
const cookie=(name)=>document.cookie.split("; ").find(x=>x.startsWith(name+"="))?.split("=")[1]||"";
function StaffManagement({api}){
 const[staff,setStaff]=useState([]),[entry,setEntry]=useState({username:"",first_name:"",password:"",role:"cashier"}),[error,setError]=useState(""),[saving,setSaving]=useState(false);
 const load=async()=>{try{setStaff(await api("/staff/"));setError("")}catch(e){setError(e.message)}};
 useEffect(()=>{load()},[]);
 const create=async(e)=>{e.preventDefault();setSaving(true);try{await api("/staff/","POST",entry);setEntry({username:"",first_name:"",password:"",role:"cashier"});await load();showToast("Staff account created")}catch(e){setError(e.message)}finally{setSaving(false)}};
 const change=async(id,patch)=>{try{await api("/staff/"+id+"/","PATCH",patch);await load();showToast(patch.password?"Password reset successfully":patch.active===false?"Account disabled":patch.active===true?"Account enabled":"Staff role updated")}catch(e){setError(e.message)}};
 return <main className="admin wider"><h1>Staff management</h1><p>Create staff accounts and control access by role. Staff must sign in using their own credentials.</p>{error&&<p className="notice">{error}</p>}
 <form className="panel staff-create" onSubmit={create}><h2>Add staff member</h2><label>Full name<input value={entry.first_name} onChange={e=>setEntry({...entry,first_name:e.target.value})} placeholder="Optional"/></label><label>Username<input required value={entry.username} onChange={e=>setEntry({...entry,username:e.target.value})}/></label><label>Temporary password (minimum 10 characters)<input required type="password" minLength={10} autoComplete="new-password" value={entry.password} onChange={e=>setEntry({...entry,password:e.target.value})}/></label><label>Role<select value={entry.role} onChange={e=>setEntry({...entry,role:e.target.value})}><option value="cashier">Cashier</option><option value="chef">Chef</option><option value="partner">Partner · reports only</option><option value="admin">Admin</option></select></label><button disabled={saving}>{saving?"Creating…":"Create account"}</button></form>
 <h2>Team members</h2><div className="staff-list">{staff.map(x=><div className="panel staff-row" key={x.id}><div><strong>{x.first_name||x.username}</strong><p>@{x.username} · {x.active?"Active":"Disabled"}</p></div><label>Role<select value={x.role==="staff"?"cashier":x.role} onChange={e=>change(x.id,{role:e.target.value})}><option value="admin">Admin</option><option value="cashier">Cashier</option><option value="chef">Chef</option><option value="partner">Partner</option></select></label><button className="secondary" onClick={async()=>{const password=await requestPassword(x.username);if(password)await change(x.id,{password})}}>Reset password</button><button className="secondary" onClick={async()=>{if(x.active&&!(await confirmAction({title:"Disable staff account?",text:"This signs "+x.username+" out and prevents them from accessing Foodoo.",confirmText:"Disable account",danger:true})))return;await change(x.id,{active:!x.active})}}>{x.active?"Disable":"Enable"}</button></div>)}</div>
 </main>
}
function KitchenQueue({api}){
 const[orders,setOrders]=useState([]),[error,setError]=useState("");
 const refresh=async()=>{try{setOrders(await api("/kitchen/"));setError("")}catch(e){setError(e.message)}};
 useEffect(()=>{refresh()},[]);
 return <main className="admin wider"><h1>Kitchen queue</h1><p>Latest paid orders and their preparation items.</p><button onClick={refresh}>Refresh queue</button>{error&&<p className="notice">{error}</p>}<div className="menu-list">{orders.map(o=><div className="panel" key={o.id}><h2>Token #{o.token_number||"—"}</h2><small>{o.paid_at?new Date(o.paid_at).toLocaleString("en-IN"):""}</small>{o.items.map((x,i)=><p key={i}>{x.quantity} × {x.name}</p>)}</div>)}</div></main>
}
function WhatsAppInbox({api}){
 const [items,SetItems]=useState([]),[loading,SetLoading]=useState(true),[error,SetError]=useState("");
 const refresh=async()=>{SetLoading(true);try{SetItems(await api("/whatsapp/inbox/"));SetError("")}catch(e){SetError(e.message)}finally{SetLoading(false)}};
 useEffect(()=>{refresh()},[]);
 return <main className="admin wider"><div className="inbox-heading"><div><h1>WhatsApp replies</h1><p>Incoming customer replies and feedback. Messages are read-only; no automatic response is sent.</p></div><button onClick={refresh} disabled={loading}>{loading?"Loading…":"Refresh"}</button></div>{error&&<p className="notice">{error}</p>}<div className="inbox-list">{items.length===0&&!loading&&<div className="panel">No WhatsApp replies have been received yet. Verify the Meta webhook and its messages subscription.</div>}{items.map(item=><article className="panel inbox-item" key={item.id}><div className="inbox-item-top"><strong>{item.sender||"Customer"}</strong><small>{new Date(item.received_at).toLocaleString("en-IN")} · {item.message_type}</small></div><p>{item.body||"Message without text"}</p></article>)}</div></main>
}
function SessionManagement({api,onLogOut}){
 const[sessions,SetSessions]=useState([]),[error,SetError]=useState(""),[busy,SetBusy]=useState(false);
 const[deviceLabel,SetDeviceLabel]=useState(()=>{try{return localStorage.getItem("foodoo_device_label")||""}catch{return ""}});
 const saveDeviceLabel=()=>{try{localStorage.setItem("foodoo_device_label",deviceLabel.trim().slice(0,60));SetError("");showToast("Device label saved")}catch{SetError("Local storage unavailable")}};
 const refresh=async()=>{try{SetSessions(await api("/auth/sessions/"));SetError("")}catch(e){SetError(e.message)}};
 useEffect(()=>{refresh()},[]);
 const revoke=async(id,current)=>{SetBusy(true);try{await api("/auth/sessions/"+id+"/","DELETE");if(current){onLogOut()}else{await refresh();showToast("Session revoked")}}catch(e){SetError(e.message)}finally{SetBusy(false)}};
 const all=async()=>{if(!(await confirmAction({title:"Sign out everywhere?",text:"All active Foodoo sessions for this account will be revoked, including this device.",confirmText:"Sign out all",danger:true})))return;SetBusy(true);try{await api("/auth/logout-all/","POST",{});onLogOut()}catch(e){SetError(e.message)}finally{SetBusy(false)}};
 return <main className="admin wider"><h1>Account sessions</h1><p>Sessions expire after 8 hours, or after 60 minutes of inactivity. You can revoke access on another device here.</p>{error&&<p className="notice">{error}</p>}<button disabled={busy} onClick={all}>Sign out on all devices</button><div className="panel"><h2>Register this browser / POS counter</h2><p>Give this browser a recognizable label, such as Cash Counter 1 or Manager Laptop. This label is not hardware verification.</p><label>Device label<input maxLength={60} value={deviceLabel} placeholder="Cash Counter 1" onChange={e=>SetDeviceLabel(e.target.value)}/></label><button onClick={saveDeviceLabel}>Save device label</button></div><div className="staff-list">{sessions.map(x=><div className="panel staff-row" key={x.id}><div><strong>{x.current?"This device":"Other session"}</strong><p>Last active: {new Date(x.last_seen_at).toLocaleString("en-IN")} · Expires: {new Date(x.expires_at).toLocaleString("en-IN")}</p></div><button className="secondary" disabled={busy} onClick={()=>revoke(x.id,x.current)}>Revoke</button></div>)}</div></main>
}
const NAV_GROUPS=[
 {title:"OPERATIONS",items:[{id:"pos",label:"Cashier POS",icon:"pos",roles:["admin","cashier","staff"]},{id:"history",label:"Order history",icon:"history",roles:["admin","cashier","staff"]},{id:"kitchen",label:"Kitchen queue",icon:"kitchen",roles:["admin","chef"]}]},
 {title:"INSIGHTS",items:[{id:"reports",label:"Sales reports",icon:"reports",roles:["admin","partner"]},{id:"inbox",label:"WhatsApp replies",icon:"inbox",roles:["admin"]}]},
 {title:"MANAGEMENT",items:[{id:"menu",label:"Menu management",icon:"menu",roles:["admin"]},{id:"staff",label:"Team & roles",icon:"staff",roles:["admin"]},{id:"admin",label:"Restaurant settings",icon:"settings",roles:["admin"]}]}
];
const ICON_PATHS={
 pos:<><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h3"/></>,
 history:<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
 kitchen:<><path d="M7 14a4 4 0 0 1-1-7.9A5 5 0 0 1 15 5a4 4 0 0 1 2 7.8V19H7z"/><path d="M7 15h10"/></>,
 reports:<><path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/></>,
 menu:<><path d="M4 5h16M4 11h16M4 17h10"/><circle cx="18" cy="17" r="2"/></>,
 staff:<><circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M17 5a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 5v1"/></>,
 settings:<><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/></>,
 sessions:<><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></>,
 inbox:<><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5c-1.4 0-2.7-.3-3.9-.9L3 21l1.9-5.6A8.5 8.5 0 1 1 21 11.5Z"/><path d="M8 11.5h9M8 15h6"/></>,
 logout:<><path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5M13 8l4 4-4 4M8 12h9"/></>,
 bars:<path d="M4 7h16M4 12h16M4 17h16"/>,
 close:<path d="M5 5l14 14M19 5L5 19"/>
};
function NavIcon({name}){return <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICON_PATHS[name]}</svg>}
function WorkspaceNav({role,tab,onNavigate,onLogout,open,onClose,restaurant,username}){
 const groups=NAV_GROUPS.map(group=>({...group,items:group.items.filter(item=>item.roles.includes(role))})).filter(group=>group.items.length);
 return <><button className={open?"sidebar-backdrop visible":"sidebar-backdrop"} onClick={onClose} aria-label="Close navigation" tabIndex={open?0:-1}/><aside className={open?"app-sidebar open":"app-sidebar"} aria-label="Main navigation">
 <div className="sidebar-brand"><div className="brand-symbol" aria-hidden="true"><span/><span/><span/><span/></div><div className="brand-wordmark">foodoo<small>RESTAURANT OS</small></div><button type="button" className="mobile-close" onClick={onClose} aria-label="Close menu"><NavIcon name="close"/></button></div>
 <div className="sidebar-location"><span className="location-overline">YOUR WORKSPACE</span><strong title={restaurant}>{restaurant||"Restaurant"}</strong><small>Restaurant operations</small></div>
 <nav className="sidebar-navigation">{groups.map(group=><section className="nav-group" key={group.title}><h2>{group.title}</h2>{group.items.map(item=><button type="button" key={item.id} className={tab===item.id?"nav-link active":"nav-link"} aria-current={tab===item.id?"page":undefined} onClick={()=>onNavigate(item.id)}><NavIcon name={item.icon}/><span>{item.label}</span>{tab===item.id&&<span className="nav-active-dot" aria-hidden="true"/>}</button>)}</section>)}</nav>
 <div className="sidebar-footer"><button className={tab==="sessions"?"nav-link active":"nav-link"} type="button" aria-current={tab==="sessions"?"page":undefined} onClick={()=>onNavigate("sessions")}><NavIcon name="sessions"/><span>Account sessions</span></button><button className="nav-link logout-link" type="button" onClick={()=>{onClose();onLogout()}}><NavIcon name="logout"/><span>Sign out</span></button><div className="sidebar-user"><span className="user-avatar">{(username||"U").slice(0,1).toUpperCase()}</span><div><strong>{username}</strong><small>{role==="staff"?"Cashier":role==="partner"?"Partner / viewer":role.charAt(0).toUpperCase()+role.slice(1)}</small></div><span className="online-indicator" aria-label="Signed in"/></div></div>
 </aside></>
}
const PAGE_TITLES={pos:"Cashier POS",history:"Order history",kitchen:"Kitchen queue",reports:"Sales reports",inbox:"WhatsApp replies",menu:"Menu management",staff:"Team & roles",admin:"Restaurant settings",sessions:"Account sessions"};
function App(){
const historyRequest=useRef(0),reportRequest=useRef(0);
const customerLookupRequest=useRef(0);
const customerSelection=useRef(null);
const[navOpen,SetNavOpen]=useState(false);
const navigate=(page)=>{T(page);SetNavOpen(false);window.scrollTo({top:0,behavior:"instant"});};
useEffect(()=>{if(!navOpen)return;const handler=(event)=>{if(event.key==="Escape")SetNavOpen(false)};document.addEventListener("keydown",handler);return()=>document.removeEventListener("keydown",handler)},[navOpen]);
const[tokenStatus,SetTokenStatus]=useState(null),[servingInput,SetServingInput]=useState(""),[history,SetHistory]=useState(null),[report,SetReport]=useState(null),[filterQ,SetFilterQ]=useState(""),[filterStatus,SetFilterStatus]=useState("all"),[rangeStart,SetRangeStart]=useState(()=>{const d=new Date();d.setDate(d.getDate()-29);return d.toLocaleDateString("en-CA")}),[rangeEnd,SetRangeEnd]=useState(()=>new Date().toLocaleDateString("en-CA")),[historyPage,SetHistoryPage]=useState(1),[historyLoading,SetHistoryLoading]=useState(false),[showPassword,SetShowPassword]=useState(false),[photoName,SetPhotoName]=useState(""),[uploading,SetUploading]=useState(false),[booting,SetBooting]=useState(true),[loggingIn,SetLoggingIn]=useState(false),[suggestions,SetSuggestions]=useState([]),[paymentMethod,SetPaymentMethod]=useState("cash"),[phoneLookup,SetPhoneLookup]=useState(""),[search,Search]=useState(""),[editing,E]=useState(null),[username,U]=useState("admin"),[password,P]=useState(""),[auth,A]=useState(""),[me,M]=useState(null),[profile,S]=useState(null),[menu,Q]=useState([]),[cart,C]=useState({}),[customer,N]=useState({customer_name:"",customer_phone:""}),[order,O]=useState(null),[sendingWhatsapp,SetSendingWhatsapp]=useState(false),[whatsappResult,SetWhatsappResult]=useState(""),[tab,T]=useState("pos"),[newItem,I]=useState({name:"",price:"",description:"",image_url:"",food_type:"veg",food_subtype:"none",category:"main_course"}),[message,G]=useState("");
function browserDeviceLabel(){
 try{return (localStorage.getItem("foodoo_device_label")||"").slice(0,60)}catch{return ""}
}
function browserDeviceId(){
 try{
   let id=localStorage.getItem("foodoo_browser_device_id");
   if(!id){id=crypto.randomUUID();localStorage.setItem("foodoo_browser_device_id",id)}
   return id;
 }catch{return ""}
}
async function api(path,method="GET",body){
 const r=await fetch(API+path,{method,credentials:"same-origin",headers:{"Content-Type":"application/json",...(method!=="GET"?{"X-Foodoo-Device-ID":browserDeviceId(),"X-Foodoo-Device-Label":browserDeviceLabel()}:{}),...(method!=="GET"?{"X-CSRFToken":decodeURIComponent((cookie("foodoo_csrf")||cookie("csrftoken")))}:{})},...(body!==undefined?{body:JSON.stringify(body)}:{})});
 const d=await r.json().catch(()=>({}));
 if(!r.ok){const detail=typeof d.detail==="string"?d.detail:d.detail?JSON.stringify(d.detail):Object.entries(d).map(([key,value])=>key+": "+value).join("; ");throw new Error(detail||"Request failed")}
 return d
}
async function loadAccount(){const [m,r]=await Promise.all([api("/me/"),api("/restaurant/")]);M(m);S(r);Q(["admin","cashier","staff"].includes(m.role)?await api("/menu/"):[]);T(m.role==="chef"?"kitchen":m.role==="partner"?"reports":"pos")}
useEffect(()=>{let active=true;(async()=>{try{await api("/auth/csrf/");await loadAccount()}catch(e){if(active)M(null)}finally{if(active)SetBooting(false)}})();return()=>{active=false}},[]);
async function login(){if(!username.trim()||!password){G("Enter username and password");return}SetLoggingIn(true);try{await api("/auth/csrf/");await api("/auth/login/","POST",{username,password});await loadAccount();P("");G("")}catch(e){G(e.message)}finally{SetLoggingIn(false)}}
async function signOut(){try{await api("/auth/logout/","POST",{})}catch(e){}M(null);S(null);Q([]);C({});O(null);P("");G("");T("pos")}
async function refresh(){S(await api("/restaurant/"));Q(await api("/menu/"))}
async function act(fn){try{await fn();G("")}catch(e){G(e.message)}}
const lines=menu.filter(x=>x.active&&cart[x.id]>0).map(x=>({...x,quantity:cart[x.id]})),sub=lines.reduce((s,x)=>s+Number(x.price)*x.quantity,0),cg=sub*Number(profile?.cgst_rate||0)/100,sg=sub*Number(profile?.sgst_rate||0)/100;
const add=(id,delta)=>C(v=>({...v,[id]:Math.max(0,(v[id]||0)+delta)}));
async function createOrder(){await act(async()=>{const r=await api("/orders/","POST",{items:lines.map(x=>({id:x.id,quantity:x.quantity})),...customer});O(r);refreshTokens();G("Draft created. Confirm payment only after collection.")})}
async function paid(){await act(async()=>O(await api("/orders/"+order.id+"/pay/","POST",{payment_method:paymentMethod})))}
async function sendWhatsappReceipt(){if(!order||order.status!=="paid")return;SetSendingWhatsapp(true);try{const result=await api("/orders/"+order.id+"/whatsapp/","POST",{confirm:true});SetWhatsappResult("WhatsApp receipt submitted to Meta: "+result.message_id);G("")}catch(e){G(e.message)}finally{SetSendingWhatsapp(false)}}
async function lookupCustomer(phone){
 const value=phone.trim();
 if(!value||value.length<8||customerSelection.current===value)return;
 const seq=++customerLookupRequest.current;
 try{
  const r=await api("/customers/lookup/?phone="+encodeURIComponent(value));
  if(seq!==customerLookupRequest.current||customerSelection.current===value)return;
  SetPhoneLookup(r.customer_name?"Returning customer found":"");
  if(r.customer_name)N(v=>v.customer_phone.trim()===value?{...v,customer_name:r.customer_name,whatsapp_consent:!!r.whatsapp_consent}:v)
 }catch(e){if(seq===customerLookupRequest.current)SetPhoneLookup("")}
}
useEffect(()=>{
 const phone=customer.customer_phone.trim();
 if(!me||order||phone.length<3||customerSelection.current===phone){SetSuggestions([]);return}
 let cancelled=false;
 const timer=setTimeout(async()=>{
  try{
   const r=await api("/customers/suggest/?q="+encodeURIComponent(phone));
   if(!cancelled&&customerSelection.current!==phone)SetSuggestions(r)
  }catch(e){if(!cancelled)SetSuggestions([])}
 },220);
 return()=>{cancelled=true;clearTimeout(timer)}
},[customer.customer_phone,me,order]);
async function fetchHistory(page=1){const seq=++historyRequest.current;SetHistoryLoading(true);try{const qs=new URLSearchParams({start:rangeStart,end:rangeEnd,status:filterStatus,q:filterQ,page:String(page)});const data=await api("/orders/history/?"+qs);if(historyRequest.current===seq){SetHistory(data);SetHistoryPage(page);G("")}}catch(e){if(historyRequest.current===seq)G(e.message)}finally{if(historyRequest.current===seq)SetHistoryLoading(false)}}
async function fetchReport(){try{const qs=new URLSearchParams({start:rangeStart,end:rangeEnd});SetReport(await api("/reports/sales/?"+qs));G("")}catch(e){G(e.message)}}
useEffect(()=>{
 if(!me||tab!=="history")return;
 const seq=++historyRequest.current;
 SetHistoryLoading(true);
 const timer=setTimeout(async()=>{
  try{
   const qs=new URLSearchParams({start:rangeStart,end:rangeEnd,status:filterStatus,q:filterQ,page:"1"});
   const data=await api("/orders/history/?"+qs);
   if(historyRequest.current===seq){SetHistory(data);SetHistoryPage(1);G("")}
  }catch(e){if(historyRequest.current===seq)G(e.message)}
  finally{if(historyRequest.current===seq)SetHistoryLoading(false)}
 },filterQ?300:0);
 return()=>{clearTimeout(timer);historyRequest.current++}
},[tab,me,rangeStart,rangeEnd,filterStatus,filterQ]);
useEffect(()=>{
 if(!me||!["admin","partner"].includes(me.role)||tab!=="reports")return;
 const seq=++reportRequest.current;
 const timer=setTimeout(async()=>{
  try{
   const qs=new URLSearchParams({start:rangeStart,end:rangeEnd});
   const data=await api("/reports/sales/?"+qs);
   if(reportRequest.current===seq){SetReport(data);G("")}
  }catch(e){if(reportRequest.current===seq)G(e.message)}
 },150);
 return()=>{clearTimeout(timer);reportRequest.current++}
},[tab,me,rangeStart,rangeEnd]);
async function exportReport(format){
 try{
  const qs=new URLSearchParams({start:rangeStart,end:rangeEnd,file_type:format});
  const response=await fetch(API+"/reports/sales/export/?"+qs,{credentials:"same-origin"});
  if(!response.ok){const error=await response.json().catch(()=>({}));throw Error(error.detail||"Export failed")}
  const blob=await response.blob(),url=URL.createObjectURL(blob);
  const anchor=document.createElement("a");
  anchor.href=url;anchor.download="foodoo-sales-"+rangeStart+"-to-"+rangeEnd+"."+format;anchor.click();
  setTimeout(()=>URL.revokeObjectURL(url),60000);
 }catch(e){G(e.message)}
}
async function sendHistoryWhatsapp(item){
 if(item.status!=="paid"||!item.whatsapp_consent){G("Paid receipt and WhatsApp consent required");return}
 try{
  const state=await api("/orders/"+item.id+"/whatsapp/");
  const resent=state.status==="submitted";
  if(state.status==="sending"||state.status==="review_required"){
    G("WhatsApp receipt is pending or requires administrator review");return
  }
  const question=resent?"Resend the same PDF receipt to "+item.customer_phone+"? Meta may charge for another message.":"Send this PDF receipt to "+item.customer_phone+"?";
  if(!(await confirmAction({title:resent?"Resend WhatsApp receipt?":"Send WhatsApp receipt?",text:question,confirmText:resent?"Resend receipt":"Send receipt"})))return;
  const endpoint=resent?"/orders/"+item.id+"/whatsapp/resend/":"/orders/"+item.id+"/whatsapp/";
  const result=await api(endpoint,"POST",{confirm:true});
  G("");showToast("Receipt submitted to WhatsApp")
 }catch(e){G(e.message)}
}
async function viewOrderAudit(item){
 try{
  const data=await api("/orders/"+item.id+"/audit/");
  const creation=data.creation;
  const payment=data.payment;
  const describe=(actor)=>actor?[
    "Staff: "+actor.username+" ("+actor.role+")",
    "Device label: "+(actor.device?.device_label||"Unlabelled browser"),
    "Browser ID: "+(actor.device?.browser_device_id||"Not supplied"),
    "Observed IP: "+(actor.device?.observed_ip||"Unavailable"),
    "Browser: "+(actor.device?.user_agent||"Unknown")
  ].join("\n"):"Not recorded (older order)";
  await showAuditDetails("Created by: "+data.created_by+"\nCreated:\n"+describe(creation)+"\n\nPayment:\n"+describe(payment));
 }catch(e){G(e.message)}
}
async function downloadHistoryReceipt(item){try{const r=await fetch(API+"/orders/"+item.id+"/receipt/",{credentials:"same-origin"});if(!r.ok)throw Error("Receipt unavailable");const blob=await r.blob();const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=(item.receipt_number||"foodoo-receipt")+".pdf";a.click();setTimeout(()=>URL.revokeObjectURL(url),60000)}catch(e){G(e.message)}}
const rupees=(n)=>"₹"+Number(n||0).toFixed(2);
async function refreshTokens(){try{const data=await api("/tokens/today/");SetTokenStatus(data);SetServingInput(String(data.currently_serving))}catch(e){G(e.message)}}
async function updateServing(){await act(async()=>{const data=await api("/tokens/today/","POST",{currently_serving:Number(servingInput)});SetTokenStatus(data);SetServingInput(String(data.currently_serving))})}
useEffect(()=>{if(me&&tab==="pos")refreshTokens()},[me,tab]);
async function printReceipt(){try{const r=await fetch(API+"/orders/"+order.id+"/receipt/",{credentials:"same-origin"});if(!r.ok)throw Error("Receipt unavailable");const blob=await r.blob();const url=URL.createObjectURL(new Blob([blob],{type:"application/pdf"}));const a=document.createElement("a");a.href=url;a.download=(order.receipt_number||"foodoo-invoice")+".pdf";a.click();setTimeout(()=>URL.revokeObjectURL(url),60000)}catch(e){G(e.message)}}
if(booting)return <div className="login-shell"><div className="login loading">Loading Foodoo POS…</div></div>;
if(!me)return <div className="login-shell"><main className="login"><div className="login-mark">●● <strong>foodoo</strong></div><div className="login-eyebrow">RESTAURANT OPERATIONS</div><h1>Welcome back</h1><p className="login-subtitle">Your restaurant, ready for service.</p><form onSubmit={e=>{e.preventDefault();login()}}><label>Username<input required autoComplete="username" value={username} onChange={e=>U(e.target.value)} placeholder="Enter your username"/></label><label>Password<div className="password-wrap"><input required autoComplete="current-password" type={showPassword?"text":"password"} value={password} onChange={e=>P(e.target.value)} placeholder="Enter your password"/><button className="password-toggle" type="button" aria-label={showPassword?"Hide password":"Show password"} title={showPassword?"Hide password":"Show password"} onClick={()=>SetShowPassword(v=>!v)}><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>{!showPassword&&<path d="M3 21 21 3"/>}</svg></button></div></label><button disabled={loggingIn} type="submit">{loggingIn?"Signing in…":"Sign in to Foodoo"}</button></form>{message&&<p className="error">{message}</p>}<p className="login-footer">Secure staff access · Foodoo POS</p></main></div>;
return <div className="app-shell"><WorkspaceNav role={me.role} tab={tab} onNavigate={navigate} onLogout={signOut} open={navOpen} onClose={()=>SetNavOpen(false)} restaurant={profile?.name} username={me.username}/><div className="app-workspace"><header className="workspace-header"><button className="mobile-menu-button" type="button" onClick={()=>SetNavOpen(true)} aria-label="Open navigation"><NavIcon name="bars"/></button><div className="workspace-heading"><span className="workspace-eyebrow">FOODOO / {me.role==="partner"?"INSIGHTS":me.role==="chef"?"KITCHEN":"WORKSPACE"}</span><h1>{PAGE_TITLES[tab]||"Foodoo"}</h1></div><div className="header-context"><span className="workspace-name">{profile?.name||"Restaurant"}</span><span className="header-role">{me.role==="staff"?"Cashier":me.role==="partner"?"Viewer":me.role}</span></div></header><div className="workspace-main">{message&&<div className="notice app-notice" role="status">{message}</div>}
{tab==="inbox"&&me.role==="admin"?<WhatsAppInbox api={api}/>:tab==="sessions"?<SessionManagement api={api} onLogOut={signOut}/>:tab==="staff"&&me.role==="admin"?<StaffManagement api={api}/>:tab==="kitchen"&&["admin","chef"].includes(me.role)?<KitchenQueue api={api}/>:tab==="history"&&["admin","cashier","staff"].includes(me.role)?<main className="admin wider"><h1>Order history</h1><p>Review previous orders, their payment methods and original item prices. Paid receipts can be downloaded again.</p><div className="report-filters"><label>From<input type="date" value={rangeStart} onChange={e=>SetRangeStart(e.target.value)}/></label><label>To<input type="date" value={rangeEnd} onChange={e=>SetRangeEnd(e.target.value)}/></label><label>Status<select value={filterStatus} onChange={e=>SetFilterStatus(e.target.value)}><option value="all">All orders</option><option value="paid">Paid</option><option value="draft">Draft</option></select></label><label>Search<input placeholder="Phone, name or receipt" value={filterQ} onChange={e=>SetFilterQ(e.target.value)}/></label></div>{historyLoading&&<p>Loading orders…</p>}{history&&<><p>{history.count} matching orders · Page {history.page}</p><div className="history-list">{history.results.map(o=><details className="history-entry" key={o.id}><summary><span><b>Order #{o.id}</b><small>{new Date(o.created_at).toLocaleString("en-IN")}</small></span><span>{o.customer_name||"Walk-in"}{o.customer_phone?" · "+o.customer_phone:""}</span><span>{o.payment_method?o.payment_method.toUpperCase():"—"} · {o.status}</span><strong>{rupees(o.total)}</strong></summary><div className="history-detail"><p>{o.receipt_number||"Draft — no receipt yet"}</p>{o.items.map((x,i)=><p key={i}>{x.name} × {x.quantity} <b>{rupees(x.total)}</b></p>)}<p>Subtotal {rupees(o.subtotal)} · CGST {rupees(o.cgst)} · SGST {rupees(o.sgst)}</p><p className="history-creator">Created by: <strong>{o.created_by_username||"Unknown"}</strong></p>{o.status==="paid"&&<div className="history-actions"><button onClick={()=>downloadHistoryReceipt(o)}>Download receipt</button><button className="secondary" disabled={!o.whatsapp_consent||!o.customer_phone} onClick={()=>sendHistoryWhatsapp(o)}>Send / resend WhatsApp</button>{!o.whatsapp_consent&&<small>WhatsApp consent was not recorded for this order</small>}</div>}{me.role==="admin"&&<button className="secondary audit-button" onClick={()=>viewOrderAudit(o)}>View order audit</button>}</div></details>)}</div><div className="pagination"><button className="secondary" disabled={historyPage<=1||historyLoading} onClick={()=>fetchHistory(historyPage-1)}>Previous</button><button className="secondary" disabled={historyPage*history.page_size>=history.count||historyLoading} onClick={()=>fetchHistory(historyPage+1)}>Next</button></div></>}</main>:tab==="reports"&&["admin","partner"].includes(me.role)?<main className="admin wider"><h1>Sales reports</h1><p>Paid orders only · Totals reflect the original tax and payment snapshots.</p><div className="report-filters"><label>From<input type="date" value={rangeStart} onChange={e=>SetRangeStart(e.target.value)}/></label><label>To<input type="date" value={rangeEnd} onChange={e=>SetRangeEnd(e.target.value)}/></label><button onClick={()=>exportReport("csv")}>Download CSV</button><button className="secondary" onClick={()=>exportReport("xlsx")}>Download Excel</button></div>{report&&<><div className="report-stats"><article><small>Paid orders</small><strong>{report.orders}</strong></article><article><small>Total sales</small><strong>{rupees(report.revenue)}</strong></article><article><small>CGST collected</small><strong>{rupees(report.cgst)}</strong></article><article><small>SGST collected</small><strong>{rupees(report.sgst)}</strong></article></div><h2>Payment breakdown</h2><div className="panel">{report.payment_methods.length?report.payment_methods.map(x=><div className="report-line" key={x.method}><span>{(x.method||"Unknown").toUpperCase()} · {x.orders} orders</span><b>{rupees(x.revenue)}</b></div>):<p>No paid orders in this period.</p>}</div><h2>Daily sales</h2><div className="panel">{report.daily.length?report.daily.map(x=><div className="report-line" key={x.date}><span>{x.date} · {x.orders} orders</span><b>{rupees(x.revenue)}</b></div>):<p>No sales to display.</p>}</div></>}</main>:tab==="menu"&&me.role==="admin"?<main className="admin"><h1>Menu management</h1><p>Add dishes with prices, classification, descriptions and photos.</p><div className="panel"><h2>{editing?"Edit dish":"Add dish"}</h2><label>Dish name<input value={newItem.name} onChange={e=>I({...newItem,name:e.target.value})}/></label><label>Price (₹)<input type="number" min="0" step="0.01" value={newItem.price} onChange={e=>I({...newItem,price:e.target.value})}/></label><label>Food type<select value={newItem.food_type} onChange={e=>I({...newItem,food_type:e.target.value,food_subtype:"none"})}>{[["veg","Veg"],["non_veg","Non-veg"]].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label>Food subtype<select value={newItem.food_subtype||"none"} onChange={e=>I({...newItem,food_subtype:e.target.value})}>{(newItem.food_type==="veg"?[["none","None"],["paneer","Paneer"],["mushroom","Mushroom"],["other","Other"]]:[["none","None"],["egg","Egg"],["chicken","Chicken"],["mutton","Mutton"],["fish","Fish"],["other","Other"]]).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label>Menu category<select value={newItem.category} onChange={e=>I({...newItem,category:e.target.value})}>{[["snack","Snack"],["beverage","Beverage"],["combo","Combo"],["main_course","Main course"],["starter","Starter"],["dessert","Dessert"],["breakfast","Breakfast"],["other","Other"]].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label>Description<textarea value={newItem.description} onChange={e=>I({...newItem,description:e.target.value})}/></label><label>Image URL (optional alternative to uploading)<input type="url" placeholder="https://..." value={newItem.image_url} onChange={e=>I({...newItem,image_url:e.target.value,image_data:""})}/></label><label>Dish photo — choose a file (PNG, JPEG or WebP, up to 4 MB)<input type="file" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" onChange={e=>{const file=e.target.files?.[0];if(!file)return;SetPhotoName(file.name);if(!["image/png","image/jpeg","image/webp"].includes(file.type)){G("Select a PNG, JPEG or WebP image");return}if(file.size>4*1024*1024){G("Image must be 4 MB or smaller");return}SetUploading(true);const reader=new FileReader();reader.onload=()=>{I(v=>({...v,image_data:String(reader.result),image_url:""}));SetUploading(false);G("Photo selected: "+file.name+" — click Save changes or Add dish")};reader.onerror=()=>{SetUploading(false);SetPhotoName("");G("Could not read photo")};reader.readAsDataURL(file)}}/></label>{newItem.image_data&&<div className="photo-picked"><img className="restaurant-logo-preview" src={newItem.image_data} alt="Selected dish photo preview"/><span>✓ {photoName||"Image selected"} — ready to save</span></div>}<button disabled={uploading} onClick={()=>act(async()=>{if(editing){await api("/menu/"+editing+"/","PATCH",newItem)}else{await api("/menu/","POST",newItem)}E(null);SetPhotoName("");I({name:"",price:"",description:"",image_url:"",image_data:"",food_type:"veg",food_subtype:"none",category:"main_course"});await refresh()})}>{uploading?"Reading photo…":editing?"Save changes":"Add dish"}</button>{editing&&<button className="secondary" onClick={()=>{E(null);I({name:"",price:"",description:"",image_url:"",image_data:"",food_type:"veg",food_subtype:"none",category:"main_course"})}}>Cancel edit</button>}</div><h2>Current menu</h2><p>Archived dishes are hidden from the cashier, while existing orders keep their original item snapshots.</p><div className="menu-list">{menu.map(x=><div className="menu-row" key={x.id}>{(x.image_data||x.image_url)?<img src={x.image_data||x.image_url} alt={x.name}/>:<div className="small-placeholder">No photo</div>}<div><strong>{x.name} {!x.active&&"(Archived)"}</strong><p>{x.description}</p><p>{(x.food_type||"veg").replace("_"," ")}{x.food_subtype&&x.food_subtype!=="none"?" · "+x.food_subtype:""} · {(x.category||"main_course").replace("_"," ")}</p><b>₹{x.price}</b></div><button className="secondary" onClick={()=>{E(x.id);SetPhotoName(x.image_data?"Saved image":"");I({name:x.name,price:x.price,description:x.description||"",image_url:x.image_url||"",image_data:x.image_data||"",food_type:x.food_type||"veg",food_subtype:x.food_subtype||"none",category:x.category||"main_course"});window.scrollTo(0,0)}}>Edit</button><button className="secondary" onClick={()=>act(async()=>{if(!(await confirmAction({title:x.active?"Archive menu item?":"Restore menu item?",text:(x.active?"Hide ":"Make available again: ")+x.name,confirmText:x.active?"Archive item":"Restore item",danger:x.active})))return;await api("/menu/"+x.id+"/","PATCH",{active:!x.active});await refresh();showToast(x.active?"Menu item archived":"Menu item restored")})}>{x.active?"Archive":"Restore"}</button></div>)}</div></main>:tab==="admin"&&me.role==="admin"?<main className="admin"><h1>Restaurant settings</h1><p>Business details and tax configuration.</p><div className="panel">{[["name","Restaurant name"],["address","Address / location"],["contact_phone","Phone"],["gstin","GSTIN"],["fssai_license_number","FSSAI license number (14 digits)"],["branch_name","Branch name"],["branch_code","Branch code"],["cgst_rate","CGST (%)"],["sgst_rate","SGST (%)"]].map(([k,label])=><label key={k}>{label}<input value={profile[k]||""} onChange={e=>S({...profile,[k]:e.target.value})}/></label> )}<label>Branch designation<select value={profile.branch_type||"main"} onChange={e=>S({...profile,branch_type:e.target.value})}><option value="main">Main location</option><option value="branch">Branch</option></select></label><label>Restaurant logo (PNG/JPEG, under 150 KB)<input type="file" accept="image/png,image/jpeg" onChange={async e=>{const file=e.target.files?.[0];if(!file)return;if(file.size>150000){G("Logo must be smaller than 150 KB");return}const reader=new FileReader();reader.onload=()=>S(p=>({...p,logo_data:reader.result}));reader.readAsDataURL(file)}}/></label>{profile.logo_data&&<><img className="restaurant-logo-preview" src={profile.logo_data} alt="Restaurant logo"/><button className="secondary" onClick={()=>S({...profile,logo_data:""})}>Remove logo</button></>}<button onClick={()=>act(async()=>{const updated=await api("/restaurant/","PATCH",Object.fromEntries(["name","address","contact_phone","gstin","fssai_license_number","logo_data","branch_type","branch_name","branch_code","cgst_rate","sgst_rate"].map(k=>[k,profile[k]??""])));S(updated);showToast("Restaurant settings saved");})}>Save settings</button></div></main>:<main className="layout"><section className="catalog"><h1>New order</h1><p>Select items from the menu</p><input className="menu-search" type="search" placeholder="Search dishes by name or description..." value={search} onChange={e=>Search(e.target.value)}/><div className="products">{menu.filter(x=>x.active&&(x.name+" "+(x.description||"")).toLowerCase().includes(search.toLowerCase())).map(x=><article key={x.id}>{(x.image_data||x.image_url)?<img className="dish-image" src={x.image_data||x.image_url} alt={x.name}/>:<div className="placeholder">FOODOO</div>}<strong>{x.name}</strong><p className="dish-description">{x.description}</p><p className="dish-description">{(x.food_type||"veg").replace("_"," ")}{x.food_subtype&&x.food_subtype!=="none"?" · "+x.food_subtype:""} · {(x.category||"main_course").replace("_"," ")}</p><p>₹{x.price}</p><button onClick={()=>add(x.id,1)}>+ Add</button></article>)}</div></section><aside className="cart"><h2>Current order</h2><div className="token-queue"><b>Today's token queue</b><p>Now serving <strong>#{tokenStatus?.currently_serving??0}</strong> · Issued <strong>#{tokenStatus?.last_issued??0}</strong></p><div className="token-controls"><input type="number" min="0" max={tokenStatus?.last_issued??0} aria-label="Currently serving token" value={servingInput} onChange={e=>SetServingInput(e.target.value)}/><button onClick={updateServing}>Update</button><button className="secondary" onClick={refreshTokens} aria-label="Refresh token queue">↻</button></div></div>{order?<><p>Order #{order.id} · {order.status}</p>{order.token_number&&<h2 className="order-token">TOKEN #{order.token_number}</h2>}<h2>₹{order.total}</h2>{order.status==="paid"?<><button onClick={printReceipt}>Download PDF invoice</button><button disabled={sendingWhatsapp||!order.whatsapp_consent||!!whatsappResult} onClick={sendWhatsappReceipt}>{sendingWhatsapp?"Sending receipt…":whatsappResult?"WhatsApp receipt submitted":order.whatsapp_consent?"Send receipt on WhatsApp":"WhatsApp consent required"}</button>{whatsappResult&&<small>{whatsappResult}</small>}</>:<><label>Payment method<select value={paymentMethod} onChange={e=>SetPaymentMethod(e.target.value)}><option value="cash">Cash</option><option value="card">Card</option><option value="upi">UPI</option></select></label><button onClick={paid}>Confirm {paymentMethod.toUpperCase()} payment received</button></>}<button className="secondary" onClick={()=>{O(null);SetWhatsappResult("");C({});N({customer_name:"",customer_phone:"",whatsapp_consent:false})}}>New order</button></>:<>{lines.map(x=><div className="line" key={x.id}><span>{x.name}<small>₹{x.price}</small></span><button onClick={()=>add(x.id,-1)}>−</button><strong>{x.quantity}</strong><button onClick={()=>add(x.id,1)}>+</button></div>)}<label>Customer phone<input inputMode="tel" value={customer.customer_phone} onChange={e=>{customerSelection.current=null;customerLookupRequest.current++;SetSuggestions([]);N({...customer,customer_phone:e.target.value,customer_name:""});SetPhoneLookup("")}} onBlur={e=>lookupCustomer(e.target.value)}/></label>{suggestions.length>0&&<div className="phone-suggestions">{suggestions.map(x=><button type="button" key={x.customer_phone} onMouseDown={e=>e.preventDefault()} onClick={()=>{customerSelection.current=x.customer_phone.trim();customerLookupRequest.current++;N(v=>({...v,customer_phone:x.customer_phone,customer_name:x.customer_name,whatsapp_consent:!!x.whatsapp_consent}));SetSuggestions([]);SetPhoneLookup("Returning customer selected")}}><strong>{x.customer_phone}</strong><span>{x.customer_name}</span></button>)}</div>}{phoneLookup&&<small>{phoneLookup}</small>}<label>Customer name<input value={customer.customer_name} onChange={e=>N({...customer,customer_name:e.target.value})}/></label><label className="consent"><input type="checkbox" checked={!!customer.whatsapp_consent} onChange={e=>N({...customer,whatsapp_consent:e.target.checked})}/> Customer agrees to receive this receipt on WhatsApp</label><div className="totals"><p>Subtotal <b>₹{sub.toFixed(2)}</b></p><p>CGST ({profile.cgst_rate}%) <b>₹{cg.toFixed(2)}</b></p><p>SGST ({profile.sgst_rate}%) <b>₹{sg.toFixed(2)}</b></p><h2>Total <b>₹{(sub+cg+sg).toFixed(2)}</b></h2></div><label>Payment method<select value={paymentMethod} onChange={e=>SetPaymentMethod(e.target.value)}><option value="cash">Cash</option><option value="card">Card</option><option value="upi">UPI</option></select></label><button disabled={!lines.length} onClick={createOrder}>Create order →</button></>}</aside></main>}</div></div></div>;
}
createRoot(document.getElementById("root")).render(<App/>);
