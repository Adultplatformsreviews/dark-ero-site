(function(){
  var t=document.getElementById("themeToggle");
  if(t){
    t.addEventListener("click",function(){
      var dark=document.documentElement.getAttribute("data-theme")==="dark";
      if(dark) document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme","dark");
      try{localStorage.setItem("de-theme",dark?"light":"dark")}catch(e){}
    });
  }
  var n=document.getElementById("navToggle"),p=document.getElementById("navPanel");
  if(n&&p){
    n.addEventListener("click",function(){
      var o=p.classList.toggle("open");
      n.setAttribute("aria-expanded",o?"true":"false");
      document.body.style.overflow=o?"hidden":"";
    });
    p.addEventListener("click",function(e){
      if(e.target.closest("a")){
        p.classList.remove("open");
        document.body.style.overflow="";
      }
    });
  }
})();

(function(){
  function dressScrollers(){
    document.querySelectorAll(".tpd-list").forEach(function(list){
      if(list.dataset.scroller)return;
      list.dataset.scroller="1";
      var col=list.parentElement;
      if(!col)return;
      var bar=document.createElement("div");
      bar.className="tpd-scroll";
      var thumb=document.createElement("i");
      bar.appendChild(thumb);
      col.appendChild(bar);
      function place(){
        var overflow=list.scrollHeight-list.clientHeight;
        if(overflow<=2){bar.hidden=true;return}
        bar.hidden=false;
        var lr=list.getBoundingClientRect(),cr=col.getBoundingClientRect();
        bar.style.top=(lr.top-cr.top)+"px";
        bar.style.height=lr.height+"px";
        var th=Math.max(28,lr.height*(list.clientHeight/list.scrollHeight));
        thumb.style.height=th+"px";
        var travel=Math.max(1,lr.height-th);
        thumb.style.transform="translateY("+((list.scrollTop/overflow)*travel)+"px)";
      }
      place();
      list.addEventListener("scroll",place);
      var startY=null,startTop=0;
      thumb.addEventListener("pointerdown",function(e){
        startY=e.clientY;startTop=list.scrollTop;thumb.setPointerCapture(e.pointerId);e.preventDefault();
      });
      thumb.addEventListener("pointermove",function(e){
        if(startY==null)return;
        var overflow=list.scrollHeight-list.clientHeight;
        var travel=Math.max(1,list.clientHeight-thumb.offsetHeight);
        list.scrollTop=startTop+(e.clientY-startY)*(overflow/travel);
      });
      thumb.addEventListener("pointerup",function(){startY=null});
      window.addEventListener("resize",place);
    });
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",dressScrollers);
  else dressScrollers();
  window.addEventListener("load",dressScrollers);
})();

