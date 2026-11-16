    function normalizeTheme(name) { return name === 'light' ? 'white' : name; }
    function setTheme(name) { name = normalizeTheme(name); document.documentElement.setAttribute('data-theme', name); try { localStorage.setItem('arachne-theme', name); } catch (e) {} }
    (function () { let t = 'dracula'; try { t = normalizeTheme(localStorage.getItem('arachne-theme') || 'dracula'); } catch (e) {} document.documentElement.setAttribute('data-theme', t); var sel = document.getElementById('theme-select'); if (sel) sel.value = t; })();
  
