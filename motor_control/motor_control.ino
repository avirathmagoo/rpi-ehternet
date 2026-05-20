// ============================================================
//  Motor Control Node — Arduino Uno + W5500  —  v4.0
//
//  Changes from v3.2:
//  - FIRE protocol changed from one-shot to hold/release:
//      TYPE_FIRE_HOLD 0x03 : relay stays ON while packets arrive
//      TYPE_FIRE_OFF  0x04 : relay turns OFF immediately
//  - Relay turns OFF automatically if Pi stops sending FIRE_HOLD
//    (FIRE_WATCHDOG_MS timeout — safety guarantee)
//  - Relay turns OFF on communications watchdog timeout
//
//  PIN ASSIGNMENTS  (UNCHANGED from v3.x)
//  ───────────────
//  W5500 : CS=10, RST=9, SCK=13, MOSI=11, MISO=12  (VCC=3.3V)
//  Pin 2 : LED Red       — Disconnected / watchdog
//  Pin 3 : LED Green     — Connected
//  Pin 4 : LED Heartbeat — blinks each valid packet
//  Pin 5 : Motor A UP
//  Pin 6 : Motor A DOWN
//  Pin 7 : Motor B UP
//  Pin 8 : Motor B DOWN
//  Pin A0: RELAY output  — active HIGH while FIRE_HOLD packets arrive
//
//  LED WIRING: Arduino pin → 330Ω → LED(+) → LED(−) → GND
// ============================================================

#include <SPI.h>
#include <Ethernet.h>
#include <EthernetUdp.h>

// ── Network config ───────────────────────────────────────────
byte      mac[]   = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x01 };
IPAddress localIP (192, 168, 10, 2);
IPAddress piIP    (192, 168, 10, 1);

const unsigned int LOCAL_PORT = 5000;
const unsigned int PI_PORT    = 5001;

// ── Pins ─────────────────────────────────────────────────────
const uint8_t PIN_W5500_CS      = 10;
const uint8_t PIN_W5500_RST     =  9;
const uint8_t PIN_LED_RED       =  2;
const uint8_t PIN_LED_GREEN     =  3;
const uint8_t PIN_LED_HB        =  4;
const uint8_t PIN_MOTOR_A_UP    =  5;
const uint8_t PIN_MOTOR_A_DOWN  =  6;
const uint8_t PIN_MOTOR_B_UP    =  7;
const uint8_t PIN_MOTOR_B_DOWN  =  8;
const uint8_t PIN_RELAY         = A0;   // Relay output — active HIGH

// ── Packet constants ─────────────────────────────────────────
const uint8_t MAGIC_CMD       = 0xAB;
const uint8_t MAGIC_ACK       = 0xBA;
const uint8_t TYPE_CMD        = 0x01;
const uint8_t TYPE_HB         = 0x02;
const uint8_t TYPE_FIRE_HOLD  = 0x03;   // Relay ON — must keep arriving
const uint8_t TYPE_FIRE_OFF   = 0x04;   // Relay OFF immediately
const uint8_t CMD_STOP        = 0x00;
const uint8_t CMD_UP          = 0x01;
const uint8_t CMD_DOWN        = 0x02;
const uint8_t PKT_IN_LEN      = 6;
const uint8_t PKT_OUT_LEN     = 5;

// ── Timing ───────────────────────────────────────────────────
const unsigned long WATCHDOG_MS       = 600;   // Pi comms watchdog
const unsigned long HB_BLINK_MS       =  60;   // Heartbeat LED blink duration
// Safety: if FIRE_HOLD packets stop arriving, relay turns off after this.
// Set to slightly longer than Pi heartbeat interval (250 ms) + margin.
const unsigned long FIRE_WATCHDOG_MS  = 700;

// ── State ────────────────────────────────────────────────────
EthernetUDP   udp;
unsigned long lastPacketMs    = 0;
unsigned long hbLedOnMs       = 0;
unsigned long fireHoldLastMs  = 0;  // Last time a FIRE_HOLD packet arrived
bool          hbLedOn         = false;
bool          relayActive     = false;
bool          wasConnected    = false;
uint8_t       motorA          = CMD_STOP;
uint8_t       motorB          = CMD_STOP;

// ── Helpers ──────────────────────────────────────────────────

uint8_t xorChecksum(uint8_t *buf, uint8_t len) {
  uint8_t cs = 0;
  for (uint8_t i = 0; i < len; i++) cs ^= buf[i];
  return cs;
}

void stopAllMotors() {
  motorA = CMD_STOP;
  motorB = CMD_STOP;
  digitalWrite(PIN_MOTOR_A_UP,   HIGH);
  digitalWrite(PIN_MOTOR_A_DOWN, HIGH);
  digitalWrite(PIN_MOTOR_B_UP,   HIGH);
  digitalWrite(PIN_MOTOR_B_DOWN, HIGH);
}

void applyMotor(uint8_t pinUp, uint8_t pinDown, uint8_t cmd) {
  digitalWrite(pinUp,   (cmd == CMD_UP)   ? LOW : HIGH);
  digitalWrite(pinDown, (cmd == CMD_DOWN) ? LOW : HIGH);
}

void setRelay(bool on) {
  if (on == relayActive) return;
  relayActive = on;
  digitalWrite(PIN_RELAY, on ? HIGH : LOW);
  Serial.println(on ? F("RELAY ON") : F("RELAY OFF"));
}

void setConnected(bool connected) {
  if (connected == wasConnected) return;
  wasConnected = connected;
  digitalWrite(PIN_LED_GREEN, connected ? HIGH : LOW);
  digitalWrite(PIN_LED_RED,   connected ? LOW  : HIGH);
  if (connected) {
    Serial.println(F("STATUS: CONNECTED"));
  } else {
    Serial.println(F("STATUS: DISCONNECTED — motors and relay stopped"));
  }
}

void sendAck(uint8_t seqEcho) {
  uint8_t pkt[PKT_OUT_LEN];
  pkt[0] = MAGIC_ACK;
  pkt[1] = seqEcho;
  pkt[2] = motorA;
  pkt[3] = motorB;
  pkt[4] = xorChecksum(pkt, 4);
  udp.beginPacket(piIP, PI_PORT);
  udp.write(pkt, PKT_OUT_LEN);
  udp.endPacket();
}

const char* cmdName(uint8_t cmd) {
  if (cmd == CMD_UP)   return "UP";
  if (cmd == CMD_DOWN) return "DOWN";
  return "STOP";
}

// ── Setup ─────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Serial.println(F("Motor Control Node v4.0 starting..."));

  uint8_t outPins[] = {
    PIN_MOTOR_A_UP, PIN_MOTOR_A_DOWN,
    PIN_MOTOR_B_UP, PIN_MOTOR_B_DOWN,
    PIN_LED_GREEN, PIN_LED_RED, PIN_LED_HB,
    PIN_RELAY
  };
  for (uint8_t i = 0; i < sizeof(outPins); i++) {
    pinMode(outPins[i], OUTPUT);
    digitalWrite(outPins[i], LOW);
  }

  stopAllMotors();
  digitalWrite(PIN_RELAY,   LOW);
  digitalWrite(PIN_LED_RED, HIGH);

  pinMode(PIN_W5500_RST, OUTPUT);
  digitalWrite(PIN_W5500_RST, LOW);
  delay(100);
  digitalWrite(PIN_W5500_RST, HIGH);
  delay(500);

  Ethernet.init(PIN_W5500_CS);
  
  // Set socket timeout to prevent indefinite hang on W5500 failure
  unsigned long eth_timeout = millis() + 10000;  // 10 second timeout
  while (!Ethernet.localIP() && (millis() - eth_timeout) < 10000) {
    Ethernet.begin(mac, localIP);
    delay(500);
    if (millis() > eth_timeout) {
      Serial.println(F("ERROR: Ethernet init timeout — W5500 may be disconnected"));
      break;
    }
  }
  delay(500);

  Serial.print(F("IP address : "));
  Serial.println(Ethernet.localIP());
  Serial.print(F("Listening  : port "));
  Serial.println(LOCAL_PORT);
  Serial.println(F("Waiting for Pi heartbeat..."));

  udp.begin(LOCAL_PORT);
  lastPacketMs   = millis();
  fireHoldLastMs = millis();
}

// ── Loop ──────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  Ethernet.maintain();

  // ── Pi comms watchdog ──
  bool connected = (now - lastPacketMs) < WATCHDOG_MS;
  if (!connected) {
    stopAllMotors();
    setRelay(false);         // Safety: relay off if Pi drops out
    fireHoldLastMs = now;    // Reset so we don't false-trigger on reconnect
  }
  setConnected(connected);

  // ── FIRE hold watchdog ──
  // If relay is active but FIRE_HOLD packets stopped, turn relay off
  if (relayActive && (now - fireHoldLastMs) >= FIRE_WATCHDOG_MS) {
    setRelay(false);
    Serial.println(F("RELAY OFF — FIRE_HOLD timeout"));
  }

  // ── Heartbeat LED off ──
  if (hbLedOn && (now - hbLedOnMs > HB_BLINK_MS)) {
    hbLedOn = false;
    digitalWrite(PIN_LED_HB, LOW);
  }

  // ── Check for incoming UDP packet ──
  int pktSize = udp.parsePacket();
  if (pktSize <= 0) return;
  if (pktSize < PKT_IN_LEN) {
    while (udp.available()) udp.read();
    return;
  }

  uint8_t buf[PKT_IN_LEN];
  int bytesRead = udp.read(buf, PKT_IN_LEN);
  if (bytesRead < PKT_IN_LEN) return;

  if (buf[0] != MAGIC_CMD) return;

  if (xorChecksum(buf, PKT_IN_LEN - 1) != buf[PKT_IN_LEN - 1]) {
    Serial.println(F("Bad checksum — dropped"));
    return;
  }

  uint8_t seq  = buf[1];
  uint8_t type = buf[2];

  // Valid packet — reset comms watchdog, blink heartbeat LED
  lastPacketMs = now;
  hbLedOn      = true;
  hbLedOnMs    = now;
  digitalWrite(PIN_LED_HB, HIGH);

  if (type == TYPE_HB) {
    sendAck(seq);
    return;
  }

  if (type == TYPE_CMD) {
    uint8_t cmdA = buf[3];
    uint8_t cmdB = buf[4];

    if (cmdA > CMD_DOWN || cmdB > CMD_DOWN) {
      Serial.println(F("Invalid CMD values — dropped"));
      return;
    }

    motorA = cmdA;
    motorB = cmdB;
    applyMotor(PIN_MOTOR_A_UP, PIN_MOTOR_A_DOWN, motorA);
    applyMotor(PIN_MOTOR_B_UP, PIN_MOTOR_B_DOWN, motorB);

    Serial.print(F("CMD  A="));
    Serial.print(cmdName(motorA));
    Serial.print(F("  B="));
    Serial.println(cmdName(motorB));

    sendAck(seq);
    return;
  }

  if (type == TYPE_FIRE_HOLD) {
    fireHoldLastMs = now;   // Refresh hold watchdog
    setRelay(true);
    sendAck(seq);
    return;
  }

  if (type == TYPE_FIRE_OFF) {
    setRelay(false);
    sendAck(seq);
    return;
  }
}
