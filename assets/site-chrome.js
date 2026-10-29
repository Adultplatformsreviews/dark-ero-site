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
