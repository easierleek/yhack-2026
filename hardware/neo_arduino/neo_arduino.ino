// ============================================================
//  NEO — Nodal Energy Oracle
//  Arduino Firmware v1.0
//  YHack 2025
//
//  ROLE: Hardware I/O layer.
//    → Reads all sensors every 100 ms and sends CSV to Python.
//    → Receives command string from Python and drives:
//         PCA9685 (16-ch PWM → LEDs)
//         Relay   (Green Grid / State Grid switch)
//         LCD     (16×2 I2C status display)
//
//  SERIAL PROTOCOL
//    TX (Arduino → Python), every 100 ms:
//      "light,temp_c,pressure_hpa,solar_ma,load_ma,pot1,pot2,tilt,button\n"
//
//    RX (Python → Arduino), as available:
//      "PWM:v0,v1,...,v15,RELAY:r,LCD1:line1,LCD2:line2\n"
//
//  I2C ADDRESS MAP  (solder jumpers noted where relevant)
//    PCA9685  PWM driver    0x40  default
//    INA219   Solar sense   0x41  A0 pad bridged HIGH
//    INA219   Load  sense   0x44  A1 pad bridged HIGH
//    LCD      16×2           0x27  check back of your module
//    BMP180   Pressure      0x77  fixed
//
//  REQUIRED LIBRARIES (install via Library Manager)
//    Adafruit PWM Servo Driver Library
//    Adafruit INA219
//    Adafruit BMP085 Unified   ← covers BMP180 too
//    DHT sensor library (Adafruit)
//    LiquidCrystal I2C (Frank de Brabander)
// ============================================================

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <Adafruit_INA219.h>
#include <Adafruit_BMP085.h>
#include <DHT.h>
#include <LiquidCrystal_I2C.h>

// ─── PIN DEFINITIONS ─────────────────────────────────────────────────────────
#define LDR_PIN     A0   // Photoresistor (solar proxy)
#define POT1_PIN    A1   // Residential demand knob A
#define POT2_PIN    A2   // Residential demand knob B

#define TILT_PIN     2   // Tilt / seismic sensor  (active LOW, internal pullup)
#define BTN1_PIN     3   // Mayor button 1 — Industrial Curfew
#define BTN2_PIN     4   // Mayor button 2 — Solar Subsidy
#define BTN3_PIN     5   // Mayor button 3 — Brownout Protocol
#define BTN4_PIN     6   // Mayor button 4 — Emergency Grid
#define BTN5_PIN     8   // Mayor button 5 — Commercial Lockdown
#define RELAY_PIN    7   // Grid relay  (HIGH = State Grid active)
#define DHT_PIN      9   // DHT11 data line

#define DHT_TYPE     DHT11

// ─── OBJECTS ─────────────────────────────────────────────────────────────────
Adafruit_PWMServoDriver pca   = Adafruit_PWMServoDriver(0x40);
Adafruit_INA219          inaSolar(0x41);
Adafruit_INA219          inaLoad(0x44);
Adafruit_BMP085          bmp;
DHT                      dht(DHT_PIN, DHT_TYPE);
LiquidCrystal_I2C        lcd(0x27, 16, 2);

// ─── STATE ───────────────────────────────────────────────────────────────────
uint8_t       pwmVals[16];
uint8_t       relayState    = 0;
char          lcdLine1[17]  = "NEO BOOTING...  ";
char          lcdLine2[17]  = "PLEASE WAIT...  ";
unsigned long lastSendMs    = 0;
bool          lcdDirty      = true;    // only redraw when content changes

// Button edge-detection (send only one press event per physical press)
bool          btnWasDown[6] = {false}; // index 1-5, index 0 unused

// ─── HELPERS ─────────────────────────────────────────────────────────────────

// Map 0-255 brightness to PCA9685 12-bit count and apply to channel.
void setLED(uint8_t ch, uint8_t brightness) {
    if (ch >= 16) return;
    pwmVals[ch] = brightness;
    uint16_t cnt = map((int)brightness, 0, 255, 0, 4095);
    pca.setPWM(ch, 0, cnt);
}

// Read the 5 mayor buttons with simple debounce.
// Returns 1-5 on a fresh press, 0 if nothing new is pressed.
int readButton() {
    const uint8_t pins[6] = {0, BTN1_PIN, BTN2_PIN, BTN3_PIN, BTN4_PIN, BTN5_PIN};
    for (int i = 1; i <= 5; i++) {
        bool down = (digitalRead(pins[i]) == LOW);
        if (down && !btnWasDown[i]) {
            btnWasDown[i] = true;
            return i;
        }
        if (!down) btnWasDown[i] = false;
    }
    return 0;
}

// ─── COMMAND PARSER ──────────────────────────────────────────────────────────
// Expects: "PWM:v0,v1,...,v15,RELAY:r,LCD1:line1,LCD2:line2"
void parseCommand(String &cmd) {
    // ── PWM values ──────────────────────────────────────────────────────────
    int pStart = cmd.indexOf(F("PWM:"));
    int rMark  = cmd.indexOf(F(",RELAY:"));
    if (pStart < 0 || rMark < 0) return;
    pStart += 4;

    String pwmSec = cmd.substring(pStart, rMark);
    uint8_t idx = 0;
    int     s   = 0;
    for (int i = 0; i <= (int)pwmSec.length() && idx < 16; i++) {
        if (i == (int)pwmSec.length() || pwmSec.charAt(i) == ',') {
            int val = constrain(pwmSec.substring(s, i).toInt(), 0, 255);
            setLED(idx, (uint8_t)val);
            idx++;
            s = i + 1;
        }
    }

    // ── Relay ────────────────────────────────────────────────────────────────
    int l1Mark = cmd.indexOf(F(",LCD1:"));
    if (l1Mark < 0) return;
    uint8_t newRelay = (uint8_t)constrain(
        cmd.substring(rMark + 7, l1Mark).toInt(), 0, 1);
    if (newRelay != relayState) {
        relayState = newRelay;
        digitalWrite(RELAY_PIN, relayState ? HIGH : LOW);
    }

    // ── LCD lines ────────────────────────────────────────────────────────────
    int l2Mark = cmd.indexOf(F(",LCD2:"));
    if (l2Mark < 0) return;

    String line1 = cmd.substring(l1Mark + 6, l2Mark);
    String line2 = cmd.substring(l2Mark + 6);
    line2.trim();

    // Pad / truncate to exactly 16 chars
    while (line1.length() < 16) line1 += ' ';
    while (line2.length() < 16) line2 += ' ';
    line1 = line1.substring(0, 16);
    line2 = line2.substring(0, 16);

    // Only write to LCD hardware when content actually changed (saves I2C bus time)
    if (line1 != String(lcdLine1) || line2 != String(lcdLine2)) {
        line1.toCharArray(lcdLine1, 17);
        line2.toCharArray(lcdLine2, 17);
        lcdDirty = true;
    }
}

// ─── SETUP ───────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(9600);
    Wire.begin();

    // Outputs
    pinMode(RELAY_PIN, OUTPUT);
    digitalWrite(RELAY_PIN, LOW);

    // Inputs with internal pullup (active LOW)
    uint8_t inputPins[] = {
        TILT_PIN,
        BTN1_PIN, BTN2_PIN, BTN3_PIN, BTN4_PIN, BTN5_PIN
    };
    for (uint8_t i = 0; i < 6; i++) {
        pinMode(inputPins[i], INPUT_PULLUP);
    }

    // PCA9685 — all LEDs off
    pca.begin();
    pca.setPWMFreq(1000);   // 1 kHz — good for LEDs
    for (uint8_t i = 0; i < 16; i++) {
        pca.setPWM(i, 0, 0);
        pwmVals[i] = 0;
    }

    // INA219 sensors
    inaSolar.begin();
    inaLoad.begin();

    // BMP180
    if (!bmp.begin()) {
        // Non-fatal: Python will receive 1013.25 placeholder
    }

    // DHT11
    dht.begin();

    // LCD
    lcd.init();
    lcd.backlight();
    lcd.setCursor(0, 0); lcd.print(F("NEO BOOTING...  "));
    lcd.setCursor(0, 1); lcd.print(F("PLEASE WAIT...  "));

    // Give DHT11 time to stabilise
    delay(2000);

    lcd.setCursor(0, 0); lcd.print(F("NEO ONLINE      "));
    lcd.setCursor(0, 1); lcd.print(F("AWAITING PYTHON "));
}

// ─── MAIN LOOP ───────────────────────────────────────────────────────────────
void loop() {
    unsigned long now = millis();

    // ── Receive command from Python (non-blocking) ───────────────────────────
    if (Serial.available()) {
        String cmd = Serial.readStringUntil('\n');
        cmd.trim();
        if (cmd.startsWith(F("PWM:"))) {
            parseCommand(cmd);
        }
    }

    // ── Flush LCD if dirty ────────────────────────────────────────────────────
    if (lcdDirty) {
        lcd.setCursor(0, 0); lcd.print(lcdLine1);
        lcd.setCursor(0, 1); lcd.print(lcdLine2);
        lcdDirty = false;
    }

    // ── Send sensor snapshot every 100 ms ────────────────────────────────────
    if (now - lastSendMs >= 100) {
        lastSendMs = now;

        // ── Analog reads ────────────────────────────────────────────────────
        int  light   = analogRead(LDR_PIN);
        int  pot1    = analogRead(POT1_PIN);
        int  pot2    = analogRead(POT2_PIN);

        // ── DHT11 (temp only — humidity unused) ─────────────────────────────
        float temp_c = dht.readTemperature();
        if (isnan(temp_c)) temp_c = 25.0f;   // safe default

        // ── BMP180 pressure ─────────────────────────────────────────────────
        float pres_hpa = bmp.readPressure() / 100.0f;
        if (pres_hpa < 800.0f || pres_hpa > 1100.0f) pres_hpa = 1013.25f;

        // ── INA219 current sensors ───────────────────────────────────────────
        float solar_ma = inaSolar.getCurrent_mA();
        float load_ma  = inaLoad.getCurrent_mA();
        if (solar_ma < 0.0f) solar_ma = 0.0f;
        if (load_ma  < 0.0f) load_ma  = 0.0f;

        // ── Digital reads ────────────────────────────────────────────────────
        // Tilt switch: active LOW with pullup → invert so 1 = earthquake
        int tilt   = (digitalRead(TILT_PIN) == LOW) ? 1 : 0;
        int button = readButton();

        // ── Transmit CSV ─────────────────────────────────────────────────────
        Serial.print(light);          Serial.print(',');
        Serial.print(temp_c,    1);   Serial.print(',');
        Serial.print(pres_hpa,  1);   Serial.print(',');
        Serial.print(solar_ma,  2);   Serial.print(',');
        Serial.print(load_ma,   2);   Serial.print(',');
        Serial.print(pot1);           Serial.print(',');
        Serial.print(pot2);           Serial.print(',');
        Serial.print(tilt);           Serial.print(',');
        Serial.println(button);
    }
}