"""
Learned components for UPIN: models trained on the drone's own flights.

  inertial_net    a small network that predicts velocity and its uncertainty
  features        what it reads: one second of IMU, attitude and throttle
  flight_library  every test flight, its measured weather, the model versions
  sim_flights     SIMULATED flights, for testing the pipeline only

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""
