// ── UPIN Military HUD Demo ───────────────────────────────────────
var map, marker, accCircle, spoofMarker, jamMarker;
var isSpoofing = false, isJamming = false, isTriangulated = false;
var selectedPlatform = 'air';
var truePos = { lat: 13.082734, lon: 80.270542 };

// ── Tab Switching ────────────────────────────────────────────────
function switchTab(tab) {
    document.querySelectorAll('.tab').forEach(function(t,i){ t.classList.remove('active'); });
    event.target.classList.add('active');
    document.getElementById('tab-platforms').style.display = tab==='platforms' ? '' : 'none';
    document.getElementById('tab-layers').style.display = tab==='layers' ? '' : 'none';
    document.getElementById('tab-intel').style.display = tab==='intel' ? '' : 'none';
    if (tab==='layers') loadLayerBrowser();
    if (tab==='intel') refreshIntel();
}

// ── Layer Browser ────────────────────────────────────────────────
var allLayers = [];
function loadLayerBrowser() {
    fetch('/api/layers/list').then(function(r){return r.json()}).then(function(d){
        allLayers = d.layers;
        renderLayers(allLayers);
    }).catch(function(){ renderLayers([]); });
}
function renderLayers(layers) {
    var groups = {A:'Satellite',B:'Inertial',C:'Magnetic',D:'RF',E:'Optical',F:'Acoustic',G:'Gravity',H:'Chemical',I:'Cosmic',J:'Human',K:'Systems'};
    var html = '';
    var currentGroup = '';
    layers.forEach(function(l){
        if (l.group !== currentGroup) {
            currentGroup = l.group;
            html += '<div style="font-size:10px;color:var(--cyan);letter-spacing:2px;margin:10px 0 4px;font-weight:700">GROUP ' + l.group + ' — ' + (groups[l.group]||'') + '</div>';
        }
        html += '<div class="layer-row ' + (l.on?'on':'') + '" onclick="toggleLayer(this,\'' + l.id + '\')">';
        html += '<div><div class="lr-name">' + l.name + '</div><div class="lr-group">' + l.id + '</div></div>';
        html += '<div class="lr-toggle"></div></div>';
    });
    document.getElementById('layer-list').innerHTML = html;
}
function toggleLayer(el, id) {
    el.classList.toggle('on');
    allLayers.forEach(function(l){ if(l.id===id) l.on=!l.on; });
    var count = allLayers.filter(function(l){return l.on}).length;
    document.getElementById('layer-count').textContent = count + ' layers active';
}
function filterLayers(query) {
    var q = query.toLowerCase();
    var filtered = allLayers.filter(function(l){ return l.name.toLowerCase().indexOf(q)!==-1 || l.id.indexOf(q)!==-1 || l.group.toLowerCase().indexOf(q)!==-1; });
    renderLayers(filtered);
}

// ── Intel Input ──────────────────────────────────────────────────
var intelMarkers = [];
function addIntel() {
    var entry = {
        type: document.getElementById('intel-type').value,
        name: document.getElementById('intel-name').value || 'Unnamed',
        description: document.getElementById('intel-desc').value,
        lat: parseFloat(document.getElementById('intel-lat').value) || 13.085,
        lon: parseFloat(document.getElementById('intel-lon').value) || 80.275,
        radius_m: parseFloat(document.getElementById('intel-radius').value) || 500,
        severity: parseFloat(document.getElementById('intel-severity').value) || 0.5
    };
    fetch('/api/intel/add', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(entry)})
    .then(function(r){return r.json()})
    .then(function(d){
        // Add to map
        var color = entry.type.indexOf('SPOOF')!==-1 ? '#F44336' : entry.type.indexOf('JAM')!==-1 ? '#FF9800' : entry.type.indexOf('THREAT')!==-1||entry.type.indexOf('DANGER')!==-1 ? '#F44336' : entry.type==='SAFE_ROUTE' ? '#4CAF50' : '#00BCD4';
        var circle = L.circle([entry.lat, entry.lon], {radius: entry.radius_m, color: color, fillColor: color, fillOpacity: 0.15, weight: 1})
            .bindPopup('<b>'+entry.type+'</b><br>'+entry.name+'<br>Radius: '+entry.radius_m+'m')
            .addTo(map);
        var pin = L.circleMarker([entry.lat, entry.lon], {radius: 5, color: color, fillColor: color, fillOpacity: 0.9})
            .addTo(map);
        intelMarkers.push({id: d.intel_id, circle: circle, pin: pin});
        refreshIntel();
        document.getElementById('intel-name').value = '';
        document.getElementById('intel-desc').value = '';
    });
}
function removeIntel(id) {
    fetch('/api/intel/remove', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({intel_id:id})})
    .then(function(){
        intelMarkers.forEach(function(m){
            if(m.id===id){ map.removeLayer(m.circle); map.removeLayer(m.pin); }
        });
        intelMarkers = intelMarkers.filter(function(m){return m.id!==id});
        refreshIntel();
    });
}
function refreshIntel() {
    fetch('/api/intel/list').then(function(r){return r.json()}).then(function(d){
        var html = '';
        (d.intel||[]).forEach(function(e){
            html += '<div class="intel-entry">';
            html += '<div class="ie-info"><div class="ie-type">'+e.type+'</div><div class="ie-name">'+e.name+' ('+e.lat.toFixed(4)+'N '+e.lon.toFixed(4)+'E)</div></div>';
            html += '<button class="ie-remove" onclick="removeIntel(\''+e.intel_id+'\')">X</button>';
            html += '</div>';
        });
        if (!html) html = '<div style="text-align:center;color:#5a7a6a;padding:10px;font-size:11px">No intel entries — add above</div>';
        document.getElementById('intel-entries').innerHTML = html;
    });
}

// ── Boot ─────────────────────────────────────────────────────────
window.addEventListener('load', function () {
    initMap();
    selectPlatform('air');
    setInterval(tick, 1500);
    setInterval(updateClock, 1000);
    updateClock();
});

// ── Map ──────────────────────────────────────────────────────────
function initMap() {
    map = L.map('map', { zoomControl: false }).setView([truePos.lat, truePos.lon], 14);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: 'CartoDB Dark'
    }).addTo(map);

    marker = L.circleMarker([truePos.lat, truePos.lon], {
        radius: 6, color: '#4CAF50', fillColor: '#4CAF50', fillOpacity: 1
    }).bindPopup('UPIN Fused Position').addTo(map);

    accCircle = L.circle([truePos.lat, truePos.lon], {
        radius: 8, color: '#4CAF50', fillColor: '#4CAF50', fillOpacity: 0.12, weight: 1
    }).addTo(map);

    // Reference points
    [['Marina Beach',13.0488,80.2785],['Fort St. George',13.0797,80.2884],
     ['Chennai Central',13.0817,80.2753]].forEach(function(p){
        L.circleMarker([p[1],p[2]],{radius:3,color:'#FF9800',fillOpacity:.7})
         .bindPopup('<b>'+p[0]+'</b><br>Calibration Ref').addTo(map);
    });
}

// ── Platform Selection ───────────────────────────────────────────
function selectPlatform(p) {
    selectedPlatform = p;
    document.querySelectorAll('.platform-card').forEach(function(c){ c.classList.remove('selected'); });
    document.getElementById('card-' + p).classList.add('selected');

    // Update center sensor icons visibility
    var configs = {
        air:  { gps: true,  cell: true,  wifi: true,  imu: true, vis: true,  acou: false },
        sea:  { gps: false, cell: true,  wifi: false, imu: true, vis: false, acou: true  },
        sub:  { gps: false, cell: false, wifi: false, imu: true, vis: false, acou: true  }
    };
    var cfg = configs[p];
    for (var k in cfg) {
        var el = document.getElementById('cs-' + k);
        if (el) el.style.opacity = cfg[k] ? '1' : '.3';
    }
}

// ── Main Tick ────────────────────────────────────────────────────
function tick() {
    // Position drift
    truePos.lat += (Math.random() - 0.5) * 0.00001;
    truePos.lon += (Math.random() - 0.5) * 0.00001;
    marker.setLatLng([truePos.lat, truePos.lon]);
    accCircle.setLatLng([truePos.lat, truePos.lon]);

    // Algorithm confidences
    var algos = {};
    if (isSpoofing) {
        algos = { kalman: 23, particle: 78, fish: 94, ukf: 65, ci: 71, aco: 88 };
    } else if (isJamming) {
        algos = { kalman: 67, particle: 84, fish: 91, ukf: 78, ci: 82, aco: 86 };
    } else {
        algos = {
            kalman:   78 + Math.round((Math.random()-.5)*10),
            particle: 94 + Math.round((Math.random()-.5)*5),
            fish:     89 + Math.round((Math.random()-.5)*8),
            ukf:      85 + Math.round((Math.random()-.5)*6),
            ci:       83 + Math.round((Math.random()-.5)*7),
            aco:      92 + Math.round((Math.random()-.5)*5)
        };
    }

    // Update algo display
    var best = '', bestV = 0;
    for (var a in algos) {
        document.getElementById('v-' + a).textContent = algos[a] + '%';
        document.getElementById('algo-' + a).classList.remove('winner');
        if (algos[a] > bestV) { bestV = algos[a]; best = a; }
    }
    document.getElementById('algo-' + best).classList.add('winner');

    // Accuracy
    var acc = isSpoofing ? 15.2 : isJamming ? 12.1 : (3 + Math.random() * 5);
    accCircle.setRadius(acc);

    // Consensus display
    document.getElementById('consensus-pos').textContent =
        truePos.lat.toFixed(6) + ' N   ' + truePos.lon.toFixed(6) + ' E';
    var layers = isSpoofing ? 59 : isJamming ? 19 : 63;
    document.getElementById('consensus-acc').textContent =
        'Accuracy \u00b1' + acc.toFixed(1) + ' m  |  Layers ' + layers + '/63';

    // Status chips
    document.getElementById('chip-fusion').className = 'status-chip active';
    document.getElementById('chip-threat').className =
        'status-chip ' + (isSpoofing ? 'crit' : isJamming ? 'warn' : 'active');

    // Platform badges
    updateBadges();

    // Metrics
    document.getElementById('m-fusion').textContent = (2 + Math.random() * 4).toFixed(1) + 'ms';
    document.getElementById('m-rate').textContent = (2 + Math.random() * .5).toFixed(1) + ' Hz';
    document.getElementById('m-power').textContent = isJamming ? 'HIGH' : 'NORM';
}

function updateBadges() {
    var ids = ['air', 'sea', 'sub'];
    ids.forEach(function (p) {
        var badge = document.getElementById('badge-' + p);
        if (isSpoofing && p === 'air') {
            badge.textContent = 'SPOOFING DETECTED';
            badge.className = 'pos-badge denied';
        } else if (isJamming) {
            badge.textContent = 'GPS DENIED - NAV OK';
            badge.className = 'pos-badge denied';
        } else {
            badge.textContent = 'POSITION: CONFIRMED';
            badge.className = 'pos-badge';
        }
    });

    // Sensor icons update
    setSensorState('sensors-air', 0, isSpoofing ? 'off' : 'on');  // GPS
    setSensorState('sensors-sea', 0, isJamming ? 'off' : 'on');
}

function setSensorState(rowId, idx, state) {
    var icons = document.getElementById(rowId).children;
    if (icons[idx]) {
        icons[idx].className = 'sensor-icon ' + state;
    }
}

// ── Demo Controls ────────────────────────────────────────────────
function simSpoofing() {
    isSpoofing = !isSpoofing;
    isJamming = false;
    isTriangulated = false;
    clearMarkers();

    if (isSpoofing) {
        spoofMarker = L.circleMarker([truePos.lat + 0.015, truePos.lon + 0.02], {
            radius: 8, color: '#F44336', fillColor: '#F44336', fillOpacity: 0.8
        }).bindPopup('<b>SPOOFED POSITION</b><br>Rejected by UPIN').addTo(map);

        document.getElementById('threat-content').innerHTML =
            '<div class="threat-alert-box">' +
            '<div class="thr-title">GPS SPOOFING DETECTED</div>' +
            '<div class="thr-detail">Mahalanobis distance: 14.7 sigma<br>' +
            'GPS layer ISOLATED - 59 layers active<br>' +
            'Fish Schooling algorithm selected (94%)</div></div>';
    } else {
        document.getElementById('threat-content').innerHTML =
            '<div class="threat-ok">ALL CLEAR &mdash; NO THREATS</div>';
    }
}

function simJamming() {
    isJamming = !isJamming;
    isSpoofing = false;
    isTriangulated = false;
    clearMarkers();

    if (isJamming) {
        document.getElementById('threat-content').innerHTML =
            '<div class="threat-alert-box">' +
            '<div class="thr-title">GPS JAMMING DETECTED</div>' +
            '<div class="thr-detail">All external RF signals denied<br>' +
            'Navigating on 19 unjammable internal layers<br>' +
            'INS + Magnetic + Gravity + Muon active</div></div>';
    } else {
        document.getElementById('threat-content').innerHTML =
            '<div class="threat-ok">ALL CLEAR &mdash; NO THREATS</div>';
    }
}

function simTriangulate() {
    if (!isSpoofing && !isJamming) {
        simSpoofing();  // Start spoofing first if nothing active
    }
    isTriangulated = true;

    var jLat = truePos.lat + 0.008;
    var jLon = truePos.lon + 0.006;

    jamMarker = L.circleMarker([jLat, jLon], {
        radius: 10, color: '#FF9800', fillColor: '#FF9800', fillOpacity: 0.8
    }).bindPopup('<b>THREAT SOURCE LOCATED</b><br>' +
        jLat.toFixed(4) + 'N ' + jLon.toFixed(4) + 'E<br>Confidence: 94%').addTo(map);
    jamMarker.openPopup();

    document.getElementById('threat-content').innerHTML =
        '<div class="threat-alert-box threat-located">' +
        '<div class="thr-title">THREAT SOURCE LOCATED</div>' +
        '<div class="thr-detail">Jammer position: ' + jLat.toFixed(4) + 'N ' + jLon.toFixed(4) + 'E<br>' +
        'Triangulated from 5 sensors (TDOA)<br>' +
        'Confidence: 94% | Accuracy: &plusmn;80m<br>' +
        'Awaiting human authorisation for response</div></div>';
}

function resetDemo() {
    isSpoofing = false;
    isJamming = false;
    isTriangulated = false;
    clearMarkers();
    document.getElementById('threat-content').innerHTML =
        '<div class="threat-ok">ALL CLEAR &mdash; NO THREATS</div>';
}

function clearMarkers() {
    if (spoofMarker) { map.removeLayer(spoofMarker); spoofMarker = null; }
    if (jamMarker) { map.removeLayer(jamMarker); jamMarker = null; }
}

// ── Mission Mode ─────────────────────────────────────────────────
var currentMode = 'GHOST_RECON';
var modeRules = {
    GHOST_RECON: 'Emit: NO | Engage: NO | Lethal: NO | Autonomous: NEVER',
    SENTINEL:    'Emit: YES | Engage: NO | Lethal: NO | Autonomous: NEVER',
    GUARDIAN:    'Emit: YES | Engage: YES | Lethal: NO | Autonomous: NEVER',
    HUNTER:      'Emit: YES | Engage: YES | Lethal: YES | Autonomous: NEVER',
    COVERT_ISR:  'Emit: NO | Engage: NO | Lethal: NO | Autonomous: NEVER',
    RESCUE:      'Emit: YES | Engage: NO | Lethal: NO | Autonomous: NEVER'
};

function setMode(btn, mode) {
    currentMode = mode;
    document.querySelectorAll('.mode-btn').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
    document.getElementById('mode-rules').textContent = modeRules[mode];
    document.getElementById('m-mode').textContent = mode.split('_')[0];
    document.getElementById('chip-mode').textContent = mode.replace('_',' ');
}

// ── Precision Selector ───────────────────────────────────────────
var precisionInfo = {
    centimetre:  'Survey: UWB+LiDAR+VSLAM+LaserDoppler (9 layers)',
    submetre:    'Precision: GPS+UWB+LiDAR+VSLAM (10 layers)',
    tactical:    'Tactical: GPS+VSLAM+WiFi+Cell (10 layers)',
    navigation:  'Navigation: GPS+INS+Terrain (7 layers)',
    area:        'Area: GPS+INS+Cell (5 layers)',
    degraded:    'GPS Denied: INS+Mag+Gravity+Muon (12 layers)'
};

function setPrecision(btn, level) {
    document.querySelectorAll('.prec-btn').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
    document.getElementById('prec-info').textContent = precisionInfo[level];
}

// ── Layer Preset ─────────────────────────────────────────────────
var presetCounts = {
    minimal:7, urban:12, rural:12, maritime:13, submarine:18, aerial:12,
    gps_denied:14, all:63,
    unit_micro_uav:4, unit_small_uav:8, unit_medium_uav:13, unit_large_uav:22,
    unit_ground_vehicle:17, unit_naval_vessel:16, unit_submarine:20, unit_soldier:9,
    mission_recon:13, mission_strike:11, mission_casevac:10, mission_patrol:13, mission_covert:14
};

function loadPreset(name) {
    var count = presetCounts[name] || '?';
    document.getElementById('layer-count').textContent = count + ' layers active';
    // Update the consensus display
    document.getElementById('consensus-acc').textContent =
        'Accuracy \u00b1' + (3 + Math.random()*5).toFixed(1) + ' m  |  Layers ' + count + '/63';
}

// ── Flight Path ──────────────────────────────────────────────────
var flightPathLine = null;
var flightWaypoints = [];
var flightAnimIdx = 0;
var flightInterval = null;

function simFlightPath() {
    if (flightPathLine) {
        // Toggle off
        map.removeLayer(flightPathLine);
        flightWaypoints.forEach(function(m){ map.removeLayer(m); });
        flightPathLine = null;
        flightWaypoints = [];
        if (flightInterval) clearInterval(flightInterval);
        return;
    }

    // Define waypoints around Chennai
    var waypoints = [
        [13.0827, 80.2707],  // Start
        [13.0860, 80.2740],  // WP1
        [13.0890, 80.2700],  // WP2
        [13.0870, 80.2650],  // WP3
        [13.0840, 80.2680],  // WP4
        [13.0827, 80.2707]   // Return to start
    ];

    // Draw planned path
    flightPathLine = L.polyline(waypoints, {
        color: '#00BCD4', weight: 2, dashArray: '8 4', opacity: 0.8
    }).addTo(map);

    // Add waypoint markers
    waypoints.forEach(function(wp, i) {
        var label = i === 0 ? 'START' : i === waypoints.length-1 ? 'RTB' : 'WP' + i;
        var color = i === 0 ? '#4CAF50' : i === waypoints.length-1 ? '#FF9800' : '#00BCD4';
        var m = L.circleMarker(wp, {
            radius: 5, color: color, fillColor: color, fillOpacity: 0.9
        }).bindPopup('<b>' + label + '</b><br>' + wp[0].toFixed(4) + 'N ' + wp[1].toFixed(4) + 'E')
          .addTo(map);
        flightWaypoints.push(m);
    });

    // Animate position along path
    flightAnimIdx = 0;
    var totalSteps = waypoints.length * 20;
    flightInterval = setInterval(function() {
        flightAnimIdx++;
        if (flightAnimIdx >= totalSteps) flightAnimIdx = 0;

        var segIdx = Math.floor(flightAnimIdx / 20);
        var segProg = (flightAnimIdx % 20) / 20;
        var from = waypoints[segIdx % waypoints.length];
        var to = waypoints[(segIdx + 1) % waypoints.length];

        truePos.lat = from[0] + (to[0] - from[0]) * segProg;
        truePos.lon = from[1] + (to[1] - from[1]) * segProg;
    }, 200);

    map.fitBounds(flightPathLine.getBounds().pad(0.2));
}

// ── Phone Sensors ────────────────────────────────────────────────
var phoneActive = false;

function simPhoneSensors() {
    phoneActive = !phoneActive;
    document.getElementById('phone-panel').style.display = phoneActive ? 'block' : 'none';

    if (phoneActive && 'geolocation' in navigator) {
        navigator.geolocation.watchPosition(function(pos) {
            document.getElementById('ps-gps').textContent =
                pos.coords.latitude.toFixed(5) + ' ' + pos.coords.longitude.toFixed(5);
            truePos.lat = pos.coords.latitude;
            truePos.lon = pos.coords.longitude;
            map.setView([truePos.lat, truePos.lon], 16);
        }, function(){
            document.getElementById('ps-gps').textContent = 'Denied';
        }, { enableHighAccuracy: true });
    }

    if (phoneActive && 'DeviceMotionEvent' in window) {
        var startMotion = function() {
            window.addEventListener('devicemotion', function(e) {
                var a = e.acceleration || {};
                document.getElementById('ps-ax').textContent = (a.x||0).toFixed(2);
                document.getElementById('ps-ay').textContent = (a.y||0).toFixed(2);
                document.getElementById('ps-az').textContent = (a.z||0).toFixed(2);
                if (e.rotationRate) {
                    document.getElementById('ps-gyro').textContent = (e.rotationRate.alpha||0).toFixed(1);
                }
            });
        };
        if (typeof DeviceMotionEvent.requestPermission === 'function') {
            DeviceMotionEvent.requestPermission().then(function(p){ if(p==='granted') startMotion(); });
        } else { startMotion(); }
    }

    if (phoneActive && 'DeviceOrientationEvent' in window) {
        var startOrient = function() {
            window.addEventListener('deviceorientation', function(e) {
                document.getElementById('ps-head').textContent = (e.alpha||0).toFixed(0) + ' deg';
            });
        };
        if (typeof DeviceOrientationEvent.requestPermission === 'function') {
            DeviceOrientationEvent.requestPermission().then(function(p){ if(p==='granted') startOrient(); });
        } else { startOrient(); }
    }

    // Simulated fallback for desktop
    if (phoneActive) {
        setInterval(function() {
            if (document.getElementById('ps-ax').textContent === '--') {
                document.getElementById('ps-ax').textContent = ((Math.random()-.5)*2).toFixed(2);
                document.getElementById('ps-ay').textContent = ((Math.random()-.5)*2).toFixed(2);
                document.getElementById('ps-az').textContent = (9.8+(Math.random()-.5)).toFixed(2);
                document.getElementById('ps-head').textContent = Math.round(Math.random()*360) + ' deg';
                document.getElementById('ps-gyro').textContent = ((Math.random()-.5)*10).toFixed(1);
                if (document.getElementById('ps-gps').textContent === '--') {
                    document.getElementById('ps-gps').textContent = truePos.lat.toFixed(5) + ' ' + truePos.lon.toFixed(5);
                }
            }
        }, 500);
    }
}

// ── Clock ────────────────────────────────────────────────────────
function updateClock() {
    var now = new Date();
    var h = String(now.getHours()).padStart(2, '0');
    var m = String(now.getMinutes()).padStart(2, '0');
    var s = String(now.getSeconds()).padStart(2, '0');
    document.getElementById('clock').textContent = h + ':' + m + ':' + s + ' UTC';
}
