// Native touch panning stays native. Some X11 panels expose touches as mouse
// drags: provide a background-only fallback, never an equipment gesture.
export function enableManagementScroll() {
  document.body.classList.add('management-ui')
  let gesture=null,frame=0,ignoreClickUntil=0
  function surface(element){
    for(let node=element;node&&node!==document.body;node=node.parentElement){
      if(/auto|scroll/.test(getComputedStyle(node).overflowY)&&node.scrollHeight>node.clientHeight+1)return node
    }
    return document.scrollingElement
  }
  const stop=()=>{cancelAnimationFrame(frame);frame=0}
  document.addEventListener('pointerdown',event=>{
    stop()
    if(event.pointerType==='touch'||event.button!==0||!event.isPrimary||event.target.closest('input,select,textarea,button,a,[contenteditable],.touch-keyboard'))return
    gesture={id:event.pointerId,element:surface(event.target),start:event.clientY,y:event.clientY,time:performance.now(),speed:0,moved:false}
  })
  document.addEventListener('pointermove',event=>{
    if(!gesture||gesture.id!==event.pointerId)return
    const g=gesture,now=performance.now()
    if(!g.moved&&Math.abs(event.clientY-g.start)<10)return
    g.moved=true
    event.preventDefault()
    const delta=g.y-event.clientY,dt=Math.max(8,now-g.time)
    g.speed=.5*g.speed+.5*Math.max(-2.5,Math.min(2.5,delta/dt))
    g.element.scrollTop+=delta;g.y=event.clientY;g.time=now
  },{passive:false})
  function release(event){
    if(!gesture||event.pointerId!==gesture.id)return
    const g=gesture;gesture=null
    if(g.moved)ignoreClickUntil=performance.now()+150
    if(!g.moved||event.type==='pointercancel'||performance.now()-g.time>100||matchMedia('(prefers-reduced-motion: reduce)').matches)return
    let last=performance.now(),speed=g.speed
    function coast(now){
      const dt=Math.min(32,now-last);last=now
      const before=g.element.scrollTop;g.element.scrollTop+=speed*dt;speed*=Math.exp(-dt/150)
      if(Math.abs(speed)>.03&&g.element.scrollTop!==before)frame=requestAnimationFrame(coast)
    }
    frame=requestAnimationFrame(coast)
  }
  document.addEventListener('pointerup',release)
  document.addEventListener('pointercancel',release)
  document.addEventListener('click',event=>{
    if(performance.now()<ignoreClickUntil){event.preventDefault();event.stopPropagation()}
  },true)
  document.addEventListener('wheel',stop,{passive:true})
}
