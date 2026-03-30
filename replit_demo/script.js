// UPIN Live Demo JavaScript
class UPINLiveDemo {
    constructor() {
        this.map = null;
        this.isRunning = false;
        this.isSpoofing = false;
        this.isJamming = false;

        this.truePosition = { lat: 13.082734, lon: 80.270542 };
        this.spoofedPosition = null;
        this.jammerPosition = null;

        this.markers = { true: null, spoofed: null, jammer: null, accuracy: null };

        this.algorithms = {
            kalman:   { confidence: 0.78, accuracy: 12.3 },
            particle: { confidence: 0.94, accuracy: 6.8  },
            fish:     { confidence: 0.89, accuracy: 8.1  }
        };

        this.initMap();
        this.startSimulation();
    }

    initMap() {
        this.map = L.map('map').setView([this.truePosition.lat, this.truePosition.lon], 16);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors | UPIN Demo'
        }).addTo(this.map);

        this.addLandmarks();

        this.markers.true = L.marker(
            [this.truePosition.lat, this.truePosition.lon],
            { title: 'UPIN Consensus Position' }
        ).bindPopup('<b>UPIN Position</b><br>Multi-algorithm consensus<br>Accuracy: +/-8.5m')
         .addTo(this.map);

        this.markers.accuracy = L.circle(
            [this.truePosition.lat, this.truePosition.lon],
            { radius: 8.5, fillColor: '#4CAF50', fillOpacity: 0.2, color: '#4CAF50', weight: 2 }
        ).addTo(this.map);
    }

    addLandmarks() {
        [
            ["Marina Beach",            13.0488, 80.2785],
            ["Fort St. George",         13.0797, 80.2884],
            ["Chennai Central",         13.0817, 80.2753],
            ["Kapaleeshwarar Temple",    13.0339, 80.2697]
        ].forEach(([name, lat, lon]) => {
            L.marker([lat, lon])
             .bindPopup('<b>' + name + '</b><br>Reference Calibration Point')
             .addTo(this.map);
        });
    }

    startSimulation() {
        setInterval(() => {
            this.updateSensorData();
            this.updateAlgorithmResults();
            this.updatePerformanceMetrics();
            this.addPositionNoise();
        }, 2000);

        setInterval(() => this.updateUI(), 500);
    }

    updateSensorData() {
        var sensors = {
            gps:      this.isSpoofing ? 'SPOOFED' : 'Active',
            imu:      'Stable',
            wifi:     (Math.floor(Math.random() * 3) + 3) + ' networks',
            cellular: this.isJamming ? 'JAMMED' : 'Strong',
            mag:      (Math.floor(Math.random() * 20) + 240) + ' deg',
            baro:     (1013 + (Math.random() - 0.5) * 5).toFixed(1) + ' hPa'
        };
        document.getElementById('gps-value').textContent      = sensors.gps;
        document.getElementById('imu-value').textContent       = sensors.imu;
        document.getElementById('wifi-value').textContent      = sensors.wifi;
        document.getElementById('cellular-value').textContent  = sensors.cellular;
        document.getElementById('mag-value').textContent       = sensors.mag;
        document.getElementById('baro-value').textContent      = sensors.baro;
    }

    updateAlgorithmResults() {
        if (this.isSpoofing) {
            this.algorithms.kalman.confidence   = 0.23;
            this.algorithms.particle.confidence = 0.78;
            this.algorithms.fish.confidence     = 0.94;
        } else if (this.isJamming) {
            this.algorithms.kalman.confidence   = 0.67;
            this.algorithms.particle.confidence = 0.84;
            this.algorithms.fish.confidence     = 0.91;
        } else {
            this.algorithms.kalman.confidence   = 0.78 + (Math.random() - 0.5) * 0.10;
            this.algorithms.particle.confidence = 0.94 + (Math.random() - 0.5) * 0.05;
            this.algorithms.fish.confidence     = 0.89 + (Math.random() - 0.5) * 0.08;
        }

        document.getElementById('kalman-conf').textContent   = Math.round(this.algorithms.kalman.confidence   * 100) + '%';
        document.getElementById('particle-conf').textContent = Math.round(this.algorithms.particle.confidence * 100) + '%';
        document.getElementById('fish-conf').textContent     = Math.round(this.algorithms.fish.confidence     * 100) + '%';

        var winner = Object.entries(this.algorithms).reduce(function(best, cur) {
            return cur[1].confidence > best[1].confidence ? cur : best;
        });

        document.querySelectorAll('.algorithm-result').forEach(function(el) { el.classList.remove('winner'); });
        var idx = { kalman: 0, particle: 1, fish: 2 }[winner[0]];
        document.querySelectorAll('.algorithm-result')[idx].classList.add('winner');

        var names = { kalman: 'Kalman Filter', particle: 'Particle Filter', fish: 'Fish Schooling' };
        document.getElementById('best-algorithm').textContent = names[winner[0]];
    }

    updatePerformanceMetrics() {
        document.getElementById('fusion-speed').textContent = (2 + Math.random() * 3).toFixed(1) + 'ms';
        document.getElementById('update-rate').textContent  = (2 + Math.random() * 0.5).toFixed(1) + ' Hz';
        document.getElementById('gps-quality').textContent  = this.isSpoofing ? 'Compromised' : 'Excellent';
        document.getElementById('power-usage').textContent  = this.isJamming ? 'High' : 'Normal';
    }

    addPositionNoise() {
        var noise = 0.00001;
        this.truePosition.lat += (Math.random() - 0.5) * noise;
        this.truePosition.lon += (Math.random() - 0.5) * noise;

        if (this.markers.true) {
            this.markers.true.setLatLng([this.truePosition.lat, this.truePosition.lon]);
            this.markers.accuracy.setLatLng([this.truePosition.lat, this.truePosition.lon]);
        }

        document.getElementById('consensus-position').textContent =
            this.truePosition.lat.toFixed(6) + 'N ' + this.truePosition.lon.toFixed(6) + 'E';
    }

    updateUI() {
        document.getElementById('gps-status').className =
            this.isSpoofing ? 'indicator warning' : 'indicator active';
        document.getElementById('threat-status').className =
            (this.isSpoofing || this.isJamming) ? 'indicator critical' : 'indicator active';
        document.getElementById('fusion-status').className = 'indicator active';

        var threatLevel = this.isSpoofing ? 'HIGH' : this.isJamming ? 'MEDIUM' : 'LOW';
        var threatClass = this.isSpoofing ? 'threat-high' : this.isJamming ? 'threat-medium' : 'threat-low';
        document.getElementById('threat-level').textContent = threatLevel;
        document.getElementById('threat-level').className   = threatClass;

        var activeLayers = this.isJamming ? 5 : this.isSpoofing ? 6 : 7;
        document.getElementById('active-layers').textContent = activeLayers;

        var accuracy = this.isSpoofing ? 15.2 : this.isJamming ? 12.1 : 8.5;
        document.getElementById('current-accuracy').textContent = accuracy.toFixed(1);
        if (this.markers.accuracy) this.markers.accuracy.setRadius(accuracy);
    }
}

// ── Demo control functions ───────────────────────────────────────

function startDemo() {
    var btn = document.getElementById('start-btn');
    btn.textContent = 'Demo Running';
    btn.disabled = true;
    document.getElementById('system-status').textContent = 'Operational';
    document.getElementById('threat-alerts').innerHTML =
        '<div class="status-good">UPIN Demo Started<br><small>Multi-algorithm fusion active</small></div>';
    setTimeout(function() {
        document.getElementById('threat-alerts').innerHTML =
            '<div class="status-good">All Systems Secure<br><small>No threats detected</small></div>';
    }, 3000);
}

function simulateSpoofing() {
    var demo = window.upinDemo;
    demo.isSpoofing = !demo.isSpoofing;

    var btn = document.getElementById('spoof-btn');
    if (demo.isSpoofing) {
        btn.textContent = 'Stop Spoofing';
        btn.className   = 'demo-btn';

        demo.spoofedPosition = { lat: 13.263895, lon: 80.492137 };
        if (demo.markers.spoofed) demo.map.removeLayer(demo.markers.spoofed);
        demo.markers.spoofed = L.marker([demo.spoofedPosition.lat, demo.spoofedPosition.lon])
            .bindPopup('<b>Spoofed GPS Signal</b><br>False position injection<br>UPIN: Not fooled!')
            .addTo(demo.map);

        document.getElementById('threat-alerts').innerHTML =
            '<div class="threat-alert">' +
            'GPS SPOOFING DETECTED<br>' +
            '<strong>Threat:</strong> Position injection attack<br>' +
            '<strong>UPIN Response:</strong> Using non-GPS sensors<br>' +
            '<strong>Status:</strong> Mission continues unaffected</div>';
    } else {
        btn.textContent = 'Simulate GPS Spoofing';
        btn.className   = 'demo-btn danger';
        if (demo.markers.spoofed) { demo.map.removeLayer(demo.markers.spoofed); demo.markers.spoofed = null; }
        document.getElementById('threat-alerts').innerHTML =
            '<div class="status-good">All Systems Secure<br><small>Spoofing attack neutralized</small></div>';
    }
}

function simulateJamming() {
    var demo = window.upinDemo;
    demo.isJamming = !demo.isJamming;

    var btn = document.getElementById('jam-btn');
    if (demo.isJamming) {
        btn.textContent = 'Stop Jamming';
        btn.className   = 'demo-btn';

        demo.jammerPosition = { lat: 13.0850, lon: 80.2750 };
        if (demo.markers.jammer) demo.map.removeLayer(demo.markers.jammer);
        demo.markers.jammer = L.marker([demo.jammerPosition.lat, demo.jammerPosition.lon])
            .bindPopup('<b>GPS Jammer Detected</b><br>UPIN triangulated location<br>Confidence: 94%')
            .addTo(demo.map);

        document.getElementById('threat-alerts').innerHTML =
            '<div class="jammer-alert">' +
            'GPS JAMMING DETECTED<br>' +
            '<strong>Jammer located:</strong> 13.085N 80.275E<br>' +
            '<strong>Range:</strong> ~2.3km<br>' +
            '<strong>UPIN Status:</strong> Operating on backup sensors</div>';
    } else {
        btn.textContent = 'Simulate Jamming Attack';
        btn.className   = 'demo-btn warning';
        if (demo.markers.jammer) { demo.map.removeLayer(demo.markers.jammer); demo.markers.jammer = null; }
        document.getElementById('threat-alerts').innerHTML =
            '<div class="status-good">All Systems Secure<br><small>Jamming attack ended</small></div>';
    }
}

function resetDemo() {
    var demo = window.upinDemo;
    demo.isSpoofing = false;
    demo.isJamming  = false;

    document.getElementById('start-btn').textContent = 'Start Live Demo';
    document.getElementById('start-btn').disabled    = false;
    document.getElementById('spoof-btn').textContent = 'Simulate GPS Spoofing';
    document.getElementById('spoof-btn').className   = 'demo-btn danger';
    document.getElementById('jam-btn').textContent   = 'Simulate Jamming Attack';
    document.getElementById('jam-btn').className     = 'demo-btn warning';

    if (demo.markers.spoofed) { demo.map.removeLayer(demo.markers.spoofed); demo.markers.spoofed = null; }
    if (demo.markers.jammer)  { demo.map.removeLayer(demo.markers.jammer);  demo.markers.jammer  = null; }

    document.getElementById('threat-alerts').innerHTML =
        '<div class="status-good">All Systems Secure<br><small>Demo reset complete</small></div>';
}

// Boot
window.addEventListener('load', function() { window.upinDemo = new UPINLiveDemo(); });
