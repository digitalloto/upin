// ── UPIN Military HUD Demo ───────────────────────────────────────
var map, marker, accCircle, spoofMarker, jamMarker;
var isSpoofing = false, isJamming = false, isTriangulated = false;
var selectedPlatform = 'air';
var truePos = { lat: 13.082734, lon: 80.270542 };

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

// ── Clock ────────────────────────────────────────────────────────
function updateClock() {
    var now = new Date();
    var h = String(now.getHours()).padStart(2, '0');
    var m = String(now.getMinutes()).padStart(2, '0');
    var s = String(now.getSeconds()).padStart(2, '0');
    document.getElementById('clock').textContent = h + ':' + m + ':' + s + ' UTC';
}
