#include <Wire.h>
#include <math.h>

// SmartTrim MPU6050: Nano classic ATmega328P, SDA=A4, SCL=A5.
// 115200 baud. CSV data: timestamp_ms,roll_deg,pitch_deg
// Status/comment lines start with #. Send Z + newline to recalibrate stationary zero.
// Mount module flat, X toward forward, Y toward port or starboard consistently.
// Confirm the axis signs by gently tilting before any water testing.

const uint8_t ADDR_PRIMARY = 0x68;
const uint8_t ADDR_SECONDARY = 0x69;
const uint8_t REG_PWR_MGMT_1 = 0x6B;
const uint8_t REG_ACCEL_XOUT_H = 0x3B;
const uint8_t REG_WHO_AM_I = 0x75;
const unsigned long SAMPLE_MS = 20; // ~50 Hz
const float ALPHA = 0.98f;
const float RAD_TO_DEG_F = 57.2957795f;
uint8_t imuAddr = 0;
float gxBias = 0, gyBias = 0, gzBias = 0;
float roll = 0, pitch = 0;
float rollZero = 0, pitchZero = 0;
unsigned long lastSample = 0;
bool ready = false;

bool readRegs(uint8_t reg, uint8_t *buffer, uint8_t count) {
  Wire.beginTransmission(imuAddr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(imuAddr, count) != count) return false;
  for (uint8_t i = 0; i < count; i++) buffer[i] = Wire.read();
  return true;
}

bool writeReg(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(imuAddr);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool readIMU(float &ax, float &ay, float &az, float &gx, float &gy, float &gz) {
  uint8_t b[14];
  if (!readRegs(REG_ACCEL_XOUT_H, b, 14)) return false;
  int16_t rawAx = (int16_t)((uint16_t)b[0] << 8 | b[1]);
  int16_t rawAy = (int16_t)((uint16_t)b[2] << 8 | b[3]);
  int16_t rawAz = (int16_t)((uint16_t)b[4] << 8 | b[5]);
  int16_t rawGx = (int16_t)((uint16_t)b[8] << 8 | b[9]);
  int16_t rawGy = (int16_t)((uint16_t)b[10] << 8 | b[11]);
  int16_t rawGz = (int16_t)((uint16_t)b[12] << 8 | b[13]);
  ax = rawAx / 16384.0f; ay = rawAy / 16384.0f; az = rawAz / 16384.0f;
  gx = rawGx / 131.0f; gy = rawGy / 131.0f; gz = rawGz / 131.0f;
  return true;
}

void accelAngles(float ax, float ay, float az, float &r, float &p) {
  r = atan2(ay, az) * RAD_TO_DEG_F;
  p = atan2(-ax, sqrt(ay * ay + az * az)) * RAD_TO_DEG_F;
}

bool calibrateStationary() {
  ready = false;
  Serial.println(F("# CALIBRATING: keep vessel stationary and approximately level for 3 seconds"));
  const int N = 400;
  double sumGx = 0, sumGy = 0, sumGz = 0;
  double sumR = 0, sumP = 0;
  for (int i = 0; i < N; i++) {
    float ax, ay, az, gx, gy, gz, r, p;
    if (!readIMU(ax, ay, az, gx, gy, gz)) {
      Serial.println(F("# ERROR: sensor read during calibration"));
      return false;
    }
    accelAngles(ax, ay, az, r, p);
    sumGx += gx; sumGy += gy; sumGz += gz;
    sumR += r; sumP += p;
    delay(7);
  }
  gxBias = sumGx / N; gyBias = sumGy / N; gzBias = sumGz / N;
  rollZero = sumR / N; pitchZero = sumP / N;
  roll = rollZero; pitch = pitchZero;
  lastSample = millis();
  ready = true;
  Serial.println(F("# CALIBRATION_OK"));
  Serial.println(F("timestamp_ms,roll_deg,pitch_deg"));
  return true;
}

void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(100000);
  delay(150);
  for (uint8_t a = ADDR_PRIMARY; a <= ADDR_SECONDARY; a++) {
    imuAddr = a;
    uint8_t id;
    if (readRegs(REG_WHO_AM_I, &id, 1) && (id == 0x68 || id == 0x70 || id == 0x72)) break;
    imuAddr = 0;
  }
  if (!imuAddr) {
    Serial.println(F("# ERROR: MPU6050 not found at 0x68 or 0x69. Check power and I2C wiring."));
    return;
  }
  if (!writeReg(REG_PWR_MGMT_1, 0x00) ||
      !writeReg(0x1B, 0x00) || // gyro +/-250 deg/s
      !writeReg(0x1C, 0x00) || // accel +/-2 g
      !writeReg(0x1A, 0x03)) { // DLPF ~44 Hz accel, ~42 Hz gyro
    Serial.println(F("# ERROR: MPU6050 configuration failed"));
    return;
  }
  delay(100);
  calibrateStationary();
}

void loop() {
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'Z' || c == 'z') {
      if (imuAddr) calibrateStationary();
    }
  }
  if (!ready) { delay(100); return; }
  unsigned long now = millis();
  if ((unsigned long)(now - lastSample) < SAMPLE_MS) return;
  float dt = (unsigned long)(now - lastSample) / 1000.0f;
  lastSample = now;
  if (dt > 0.25f) { Serial.println(F("# WARN: sample gap; resetting integration interval")); dt = SAMPLE_MS / 1000.0f; }
  float ax, ay, az, gx, gy, gz;
  if (!readIMU(ax, ay, az, gx, gy, gz)) { Serial.println(F("# ERROR: I2C read failed")); return; }
  float accelRoll, accelPitch;
  accelAngles(ax, ay, az, accelRoll, accelPitch);
  // Assumes sensor X axis forward, Y lateral, Z up, initially approximately level.
  roll = ALPHA * (roll + (gx - gxBias) * dt) + (1 - ALPHA) * accelRoll;
  pitch = ALPHA * (pitch + (gy - gyBias) * dt) + (1 - ALPHA) * accelPitch;
  Serial.print(now);
  Serial.print(','); Serial.print(roll - rollZero, 3);
  Serial.print(','); Serial.println(pitch - pitchZero, 3);
}
