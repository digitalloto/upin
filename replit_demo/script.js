// ── UPIN Full Dashboard JS ────────────────────────────────────────
var map, marker, accCircle, spoofMarker, jamMarker;
var isSpoofing=false, isJamming=false;
var truePos={lat:13.082734,lon:80.270542};
var allLayers=[], intelMarkers=[], flightLine=null, flightWPs=[], flightIv=null;

window.addEventListener('load', function(){
    initMap(); loadLayerBrowser();
    setInterval(tick,1500); setInterval(updateClock,1000); updateClock();
});

// ── Tabs ──────────────────────────────────────────────────────────
function switchTab(t){
    document.querySelectorAll('.tab').forEach(function(b){b.classList.remove('active')});
    event.target.classList.add('active');
    ['platforms','layers','intel','swarm','sensors','security','ops'].forEach(function(id){
        var el=document.getElementById('tab-'+id);
        if(el) el.style.display=id===t?'':'none';
    });
    if(t==='layers') loadLayerBrowser();
    if(t==='intel') refreshIntel();
    if(t==='swarm') refreshSwarm();
    if(t==='security'){refreshIFFLog();refreshCommsLog();}
}

// ── Map ───────────────────────────────────────────────────────────
function initMap(){
    map=L.map('map',{zoomControl:false}).setView([truePos.lat,truePos.lon],14);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{attribution:'CartoDB'}).addTo(map);
    marker=L.circleMarker([truePos.lat,truePos.lon],{radius:6,color:'#4CAF50',fillColor:'#4CAF50',fillOpacity:1}).addTo(map);
    accCircle=L.circle([truePos.lat,truePos.lon],{radius:8,color:'#4CAF50',fillOpacity:.12,weight:1}).addTo(map);
    [['Marina Beach',13.0488,80.2785],['Fort St. George',13.0797,80.2884],['Chennai Central',13.0817,80.2753]].forEach(function(p){
        L.circleMarker([p[1],p[2]],{radius:3,color:'#FF9800',fillOpacity:.7}).bindPopup('<b>'+p[0]+'</b>').addTo(map);
    });
}

// ── Platform Selection ────────────────────────────────────────────
function selectPlatform(p){
    document.querySelectorAll('.platform-card').forEach(function(c){c.classList.remove('selected')});
    document.getElementById('card-'+p).classList.add('selected');
}

// ── Main Tick ─────────────────────────────────────────────────────
function tick(){
    truePos.lat+=(Math.random()-.5)*.00001; truePos.lon+=(Math.random()-.5)*.00001;
    marker.setLatLng([truePos.lat,truePos.lon]); accCircle.setLatLng([truePos.lat,truePos.lon]);
    var algos=isSpoofing?{kalman:23,particle:78,fish:94,ukf:65,ci:71,aco:88}:
              isJamming?{kalman:67,particle:84,fish:91,ukf:78,ci:82,aco:86}:
              {kalman:78+rr(10),particle:94+rr(5),fish:89+rr(8),ukf:85+rr(6),ci:83+rr(7),aco:92+rr(5)};
    var best='',bestV=0;
    for(var a in algos){document.getElementById('v-'+a).textContent=algos[a]+'%';
        document.getElementById('algo-'+a).classList.remove('winner');
        if(algos[a]>bestV){bestV=algos[a];best=a;}}
    document.getElementById('algo-'+best).classList.add('winner');
    var acc=isSpoofing?15.2:isJamming?12.1:(3+Math.random()*5);
    accCircle.setRadius(acc);
    var layers=allLayers.filter(function(l){return l.on}).length||12;
    document.getElementById('consensus-pos').textContent=truePos.lat.toFixed(6)+' N   '+truePos.lon.toFixed(6)+' E';
    document.getElementById('consensus-acc').textContent='Accuracy \u00b1'+acc.toFixed(1)+' m  |  Layers '+layers+'/63';
    document.getElementById('chip-fusion').className='status-chip active';
    document.getElementById('chip-threat').className='status-chip '+(isSpoofing?'crit':isJamming?'warn':'active');
    document.getElementById('chip-swarm').textContent='SWARM: '+document.querySelectorAll('.swarm-unit').length;
    document.getElementById('m-fusion').textContent=(2+Math.random()*4).toFixed(1)+'ms';
    document.getElementById('m-rate').textContent=(2+Math.random()*.5).toFixed(1)+' Hz';
    document.getElementById('m-power').textContent=isJamming?'HIGH':'NORM';
    updateBadges();
}
function rr(n){return Math.round((Math.random()-.5)*n)}
function updateBadges(){
    ['air','sea','sub'].forEach(function(p){
        var b=document.getElementById('badge-'+p);
        if(isSpoofing){b.textContent='SPOOFING DETECTED';b.className='pos-badge denied';}
        else if(isJamming){b.textContent='GPS DENIED';b.className='pos-badge denied';}
        else{b.textContent='POSITION: CONFIRMED';b.className='pos-badge';}
    });
}

// ── Layers ────────────────────────────────────────────────────────
function loadLayerBrowser(){
    fetch('/api/layers/list').then(function(r){return r.json()}).then(function(d){
        allLayers=d.layers; renderLayers(allLayers);
        document.getElementById('layer-count').textContent=allLayers.filter(function(l){return l.on}).length+' active';
    }).catch(function(){});
}
function renderLayers(layers){
    var groups={"A":"Satellite","B":"Inertial","C":"Magnetic","D":"RF","E":"Optical","F":"Acoustic","G":"Gravity","H":"Chemical","I":"Cosmic","J":"Human","K":"Systems"};
    var h='',cg='';
    layers.forEach(function(l){
        if(l.group!==cg){cg=l.group;h+='<div style="font-size:10px;color:var(--cyan);letter-spacing:2px;margin:8px 0 3px;font-weight:700">GROUP '+l.group+' \u2014 '+(groups[l.group]||'')+'</div>';}
        h+='<div class="layer-row '+(l.on?'on':'')+'" onclick="toggleLayer(this,\''+l.id+'\')">';
        h+='<div><div class="lr-name">'+l.name+'</div><div class="lr-group">'+l.id+(l.bio?' \u2014 '+l.bio:'')+'</div></div>';
        h+='<div class="lr-toggle"></div></div>';
    });
    document.getElementById('layer-list').innerHTML=h;
}
function toggleLayer(el,id){
    el.classList.toggle('on');
    allLayers.forEach(function(l){if(l.id===id)l.on=!l.on;});
    fetch('/api/layers/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({layer_id:id})});
    document.getElementById('layer-count').textContent=allLayers.filter(function(l){return l.on}).length+' active';
}
function filterLayers(q){q=q.toLowerCase();renderLayers(allLayers.filter(function(l){return l.name.toLowerCase().indexOf(q)!==-1||l.id.indexOf(q)!==-1||l.group.toLowerCase().indexOf(q)!==-1||(l.bio||'').toLowerCase().indexOf(q)!==-1;}));}
function loadPreset(name){if(!name)return;fetch('/api/presets/load/'+name).then(function(r){return r.json()}).then(function(d){loadLayerBrowser();});}

// ── Intel ─────────────────────────────────────────────────────────
function addIntel(){
    var e={type:gv('intel-type'),name:gv('intel-name')||'Unnamed',description:gv('intel-desc'),
           lat:parseFloat(gv('intel-lat'))||13.085,lon:parseFloat(gv('intel-lon'))||80.275,
           radius_m:parseFloat(gv('intel-radius'))||500,severity:parseFloat(gv('intel-severity'))||0.7};
    fetch('/api/intel/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(e)})
    .then(function(r){return r.json()}).then(function(d){
        var color=e.type.indexOf('SPOOF')!==-1?'#F44336':e.type.indexOf('JAM')!==-1?'#FF9800':'#00BCD4';
        var c=L.circle([e.lat,e.lon],{radius:e.radius_m,color:color,fillColor:color,fillOpacity:.12,weight:1}).addTo(map);
        var p=L.circleMarker([e.lat,e.lon],{radius:5,color:color,fillOpacity:.9}).bindPopup('<b>'+e.type+'</b><br>'+e.name).addTo(map);
        intelMarkers.push({id:d.entry.intel_id,c:c,p:p});
        refreshIntel(); sv('intel-name',''); sv('intel-desc','');
    });
}
function removeIntel(id){
    fetch('/api/intel/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({intel_id:id})})
    .then(function(){intelMarkers.forEach(function(m){if(m.id===id){map.removeLayer(m.c);map.removeLayer(m.p);}});
        intelMarkers=intelMarkers.filter(function(m){return m.id!==id});refreshIntel();});
}
function refreshIntel(){
    fetch('/api/intel/list').then(function(r){return r.json()}).then(function(d){
        var h='';(d.intel||[]).forEach(function(e){
            h+='<div class="intel-entry"><div class="ie-info"><div class="ie-type">'+e.type+'</div><div class="ie-name">'+e.name+'</div></div>';
            h+='<button class="ie-remove" onclick="removeIntel(\''+e.intel_id+'\')">X</button></div>';
        });
        document.getElementById('intel-entries').innerHTML=h||'<div style="text-align:center;color:#5a7a6a;padding:8px;font-size:10px">No intel</div>';
    });
}

// ── Swarm ─────────────────────────────────────────────────────────
function addSwarmUnit(){
    var u={name:gv('sw-name')||'Unit-'+(Math.random()*999|0),type:gv('sw-type'),role:gv('sw-role'),
           lat:parseFloat(gv('sw-lat'))||13.083,lon:parseFloat(gv('sw-lon'))||80.271};
    fetch('/api/swarm/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(u)})
    .then(function(r){return r.json()}).then(function(d){
        L.circleMarker([u.lat,u.lon],{radius:4,color:'#00BCD4',fillOpacity:.9}).bindPopup('<b>'+u.name+'</b><br>'+u.role+' ('+u.type+')').addTo(map);
        refreshSwarm();
    });
}
function refreshSwarm(){
    fetch('/api/swarm/list').then(function(r){return r.json()}).then(function(d){
        var h='';(d.units||[]).forEach(function(u){
            h+='<div class="swarm-unit"><div><span class="su-name">'+u.name+'</span> <span class="su-role">'+u.role.toUpperCase()+'</span></div>';
            h+='<div><span class="su-status">'+u.type+'</span> <button class="ie-remove" onclick="removeSwarmUnit(\''+u.unit_id+'\')">X</button></div></div>';
        });
        document.getElementById('swarm-list').innerHTML=h||'<div style="text-align:center;color:#5a7a6a;padding:8px;font-size:10px">No units</div>';
        document.getElementById('chip-swarm').textContent='SWARM: '+(d.units||[]).length;
    });
}
function removeSwarmUnit(id){fetch('/api/swarm/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({unit_id:id})}).then(refreshSwarm);}
function setFormation(){fetch('/api/swarm/formation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({formation:gv('sw-formation')})});}
function setSwarmMission(){fetch('/api/swarm/mission',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mission:gv('sw-mission')})});}

// ── Sensors ───────────────────────────────────────────────────────
function pollSensor(type){
    var urls={wifi_csi:'/api/sensors/wifi_csi',thermal:'/api/sensors/thermal',drone:'/api/sensors/drone',target_lock:'/api/sensors/target_lock'};
    var ids={wifi_csi:'feed-csi',thermal:'feed-thermal',drone:'feed-drone',target_lock:'feed-target'};
    fetch(urls[type]).then(function(r){return r.json()}).then(function(d){
        document.getElementById(ids[type]).textContent=JSON.stringify(d,null,1);
    });
}
function simPhoneSensors(){
    var pp=document.getElementById('phone-panel');
    pp.style.display=pp.style.display==='none'?'block':'none';
    if(pp.style.display==='block'){
        if('geolocation' in navigator)navigator.geolocation.watchPosition(function(p){
            document.getElementById('ps-gps').textContent=p.coords.latitude.toFixed(5)+' '+p.coords.longitude.toFixed(5);
        },function(){},{enableHighAccuracy:true});
        setInterval(function(){
            if(document.getElementById('ps-ax').textContent==='--'){
                document.getElementById('ps-ax').textContent=((Math.random()-.5)*2).toFixed(2);
                document.getElementById('ps-ay').textContent=((Math.random()-.5)*2).toFixed(2);
                document.getElementById('ps-az').textContent=(9.8+(Math.random()-.5)).toFixed(2);
                document.getElementById('ps-head').textContent=(Math.random()*360|0)+'\u00b0';
                document.getElementById('ps-gyro').textContent=((Math.random()-.5)*10).toFixed(1);
                document.getElementById('ps-gps').textContent=truePos.lat.toFixed(5)+' '+truePos.lon.toFixed(5);
            }
        },500);
    }
}

// ── Security ──────────────────────────────────────────────────────
function runIFF(){
    var t=gv('iff-target')||'UNKNOWN';
    fetch('/api/iff/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:t})})
    .then(function(r){return r.json()}).then(function(d){
        var c=d.verdict==='FRIENDLY'?'var(--green)':d.verdict==='HOSTILE'?'var(--red)':'var(--amber)';
        document.getElementById('iff-result').innerHTML='<span style="color:'+c+';font-weight:700">'+d.target+': '+d.verdict+' ('+d.factors_passed+'/7)</span>';
        refreshIFFLog();
    });
}
function refreshIFFLog(){fetch('/api/iff/log').then(function(r){return r.json()}).then(function(d){
    var h='';(d.log||[]).forEach(function(e){h+='<div style="font-size:10px;padding:2px 0;color:'+(e.verdict==='FRIENDLY'?'var(--green)':e.verdict==='HOSTILE'?'var(--red)':'var(--amber)')+'">'+e.target+': '+e.verdict+' ('+e.factors_passed+'/7)</div>';});
    document.getElementById('iff-log').innerHTML=h||'No checks yet';
});}
function sendComm(){
    fetch('/api/comms/send',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({from:gv('comm-from'),to:gv('comm-to'),classification:gv('comm-class')})})
    .then(function(){refreshCommsLog();});
}
function refreshCommsLog(){fetch('/api/comms/log').then(function(r){return r.json()}).then(function(d){
    var h='';(d.log||[]).forEach(function(e){h+='<div style="font-size:10px;padding:2px 0;color:var(--cyan)">'+e.from+' \u2192 '+e.to+' ['+e.classification+'] '+e.size_bytes+'B</div>';});
    document.getElementById('comms-log-view').innerHTML=h||'No messages';
});}
function startFalsePos(){
    fetch('/api/false_position/start',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({strategy:gv('fp-strategy'),true_lat:truePos.lat,true_lon:truePos.lon})})
    .then(function(r){return r.json()}).then(function(d){
        document.getElementById('fp-result').innerHTML='<span style="color:var(--amber)">Broadcasting: '+d.false_lat.toFixed(4)+'N '+d.false_lon.toFixed(4)+'E ('+d.strategy+')</span>';
    });
}

// ── Operations ────────────────────────────────────────────────────
var modeRules={GHOST_RECON:'Emit:NO | Engage:NO | Lethal:NO | Auto:NEVER',SENTINEL:'Emit:YES | Engage:NO | Lethal:NO | Auto:NEVER',
    GUARDIAN:'Emit:YES | Engage:YES | Lethal:NO | Auto:NEVER',HUNTER:'Emit:YES | Engage:YES | Lethal:YES | Auto:NEVER',
    COVERT_ISR:'Emit:NO | Engage:NO | Lethal:NO | Auto:NEVER',RESCUE:'Emit:YES | Engage:NO | Lethal:NO | Auto:NEVER'};
function setMode(btn,m){
    document.querySelectorAll('.mode-btn').forEach(function(b){b.classList.remove('active')});
    btn.classList.add('active');
    document.getElementById('mode-rules').textContent=modeRules[m];
    document.getElementById('m-mode').textContent=m.split('_')[0];
    document.getElementById('chip-mode').textContent=m.replace(/_/g,' ');
}
function pollPower(){fetch('/api/power/status').then(function(r){return r.json()}).then(function(d){
    document.getElementById('power-data').textContent='Battery: '+d.battery+'%  State: '+d.state+'\nLayers: '+d.active_layers+'  Power: '+d.power_mw+'mW\nRuntime: '+d.runtime_min+' min';
});}
function pollConfidence(){fetch('/api/confidence/status').then(function(r){return r.json()}).then(function(d){
    document.getElementById('conf-data').innerHTML='Confidence: <b>'+d.confidence+'%</b>  Rec: <b style="color:'+(d.recommendation==='CONTINUE'?'var(--green)':d.recommendation==='HOLD'?'var(--red)':'var(--amber)')+'">'+d.recommendation+'</b>\nDegradation: '+d.degradation_rate+' %/min  GPS: '+(d.has_gps?'YES':'NO');
});}
function checkGeofence(){
    fetch('/api/geofence/check',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({lat:parseFloat(gv('geo-lat')),lon:parseFloat(gv('geo-lon'))})})
    .then(function(r){return r.json()}).then(function(d){
        document.getElementById('geo-result').innerHTML=d.violation?'<span style="color:var(--red);font-weight:700">VIOLATION: '+d.zone+'</span>':'<span style="color:var(--green)">CLEAR</span>';
    });
}
function pollCalibration(){fetch('/api/calibration/status').then(function(r){return r.json()}).then(function(d){
    document.getElementById('cal-data').textContent='Device: '+d.device+'\nRef Points: '+d.reference_points+' ('+d.global_coverage+')\nDrift Comp: '+d.drift_compensation+'\nLast Cal: '+d.last_calibration;
});}
function pollHardening(){fetch('/api/hardening/spec').then(function(r){return r.json()}).then(function(d){
    var h='';for(var g in d.groups){var s=d.groups[g];h+=g+': '+s.weight+' | '+s.agents+' agents | '+s.hardening+'\n';}
    document.getElementById('hardening-data').textContent=h;
});}
function recordEvent(){
    var desc=gv('rec-event');if(!desc)return;
    fetch('/api/recorder/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'MANUAL',description:desc})})
    .then(function(){sv('rec-event','');refreshRecorder();});
}
function refreshRecorder(){fetch('/api/recorder/log').then(function(r){return r.json()}).then(function(d){
    var h='';(d.log||[]).forEach(function(e){h+='<div style="font-size:10px;padding:2px 0;color:#8a9a8a">'+e.event_id+': '+e.description+'</div>';});
    document.getElementById('recorder-log-view').innerHTML=h;
});}

// ── Demo Attacks ──────────────────────────────────────────────────
function simSpoofing(){isSpoofing=!isSpoofing;isJamming=false;clearMarkers();
    if(isSpoofing){spoofMarker=L.circleMarker([truePos.lat+.015,truePos.lon+.02],{radius:8,color:'#F44336',fillColor:'#F44336',fillOpacity:.8}).bindPopup('SPOOFED').addTo(map);
        document.getElementById('threat-content').innerHTML='<div class="threat-alert-box"><div class="thr-title">GPS SPOOFING DETECTED</div><div class="thr-detail">Mahalanobis: 14.7\u03c3 | GPS isolated | 59 layers active</div></div>';
    }else{document.getElementById('threat-content').innerHTML='<div class="threat-ok">ALL CLEAR</div>';}}
function simJamming(){isJamming=!isJamming;isSpoofing=false;clearMarkers();
    if(isJamming){document.getElementById('threat-content').innerHTML='<div class="threat-alert-box"><div class="thr-title">GPS JAMMING</div><div class="thr-detail">RF denied | 19 internal layers active</div></div>';
    }else{document.getElementById('threat-content').innerHTML='<div class="threat-ok">ALL CLEAR</div>';}}
function simTriangulate(){if(!isSpoofing&&!isJamming)simSpoofing();
    var jl=truePos.lat+.008,jn=truePos.lon+.006;
    jamMarker=L.circleMarker([jl,jn],{radius:10,color:'#FF9800',fillColor:'#FF9800',fillOpacity:.8}).bindPopup('<b>THREAT LOCATED</b><br>'+jl.toFixed(4)+'N '+jn.toFixed(4)+'E<br>94% confidence').addTo(map).openPopup();
    document.getElementById('threat-content').innerHTML='<div class="threat-alert-box threat-located"><div class="thr-title">THREAT SOURCE LOCATED</div><div class="thr-detail">'+jl.toFixed(4)+'N '+jn.toFixed(4)+'E | TDOA 5 sensors | 94%</div></div>';}
function simFlightPath(){
    if(flightLine){map.removeLayer(flightLine);flightWPs.forEach(function(m){map.removeLayer(m)});flightLine=null;flightWPs=[];if(flightIv)clearInterval(flightIv);return;}
    var wps=[[13.0827,80.2707],[13.086,80.274],[13.089,80.270],[13.087,80.265],[13.084,80.268],[13.0827,80.2707]];
    flightLine=L.polyline(wps,{color:'#00BCD4',weight:2,dashArray:'8 4',opacity:.8}).addTo(map);
    wps.forEach(function(w,i){var l=i===0?'START':i===wps.length-1?'RTB':'WP'+i;
        flightWPs.push(L.circleMarker(w,{radius:5,color:i===0?'#4CAF50':'#00BCD4',fillOpacity:.9}).bindPopup(l).addTo(map));});
    var ai=0,ts=wps.length*20;
    flightIv=setInterval(function(){ai=(ai+1)%ts;var si=ai/20|0,sp=(ai%20)/20;
        var f=wps[si%wps.length],t=wps[(si+1)%wps.length];
        truePos.lat=f[0]+(t[0]-f[0])*sp;truePos.lon=f[1]+(t[1]-f[1])*sp;},200);
    map.fitBounds(flightLine.getBounds().pad(.2));}
function resetDemo(){isSpoofing=false;isJamming=false;clearMarkers();
    document.getElementById('threat-content').innerHTML='<div class="threat-ok">ALL CLEAR</div>';
    if(flightLine){map.removeLayer(flightLine);flightWPs.forEach(function(m){map.removeLayer(m)});flightLine=null;flightWPs=[];if(flightIv)clearInterval(flightIv);}}
function clearMarkers(){if(spoofMarker){map.removeLayer(spoofMarker);spoofMarker=null;}if(jamMarker){map.removeLayer(jamMarker);jamMarker=null;}}

// ── Helpers ───────────────────────────────────────────────────────
function gv(id){return document.getElementById(id).value;}
function sv(id,v){document.getElementById(id).value=v;}
function updateClock(){var n=new Date();document.getElementById('clock').textContent=
    String(n.getHours()).padStart(2,'0')+':'+String(n.getMinutes()).padStart(2,'0')+':'+String(n.getSeconds()).padStart(2,'0')+' UTC';}
