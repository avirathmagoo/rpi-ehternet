// ============================================================
//  Motor Control Node — Arduino Uno + W5500
//  Version 2.0
//
//  PIN ASSIGNMENTS:
//  W5500 : CS=10, RST=9, SCK=13, MOSI=11, MISO=12
//  LEDs  : Green(connected)=3, Red(disconnected)=2, Heartbeat=8
//  Motors: A_UP=4, A_DOWN=5, B_UP=6, B_DOWN=7
// ============================================================

#include <SPI.h>
#include <Ethernet.h>
#include <EthernetUdp.h>

// ── Network config ───────────────────────────────────────────
byte        mac[]     = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x01 };
IPAddress   localIP   (192, 168, 10, 2);
IPAddress   piIP      (192, 168, 10, 1);
const unsigned int LOCAL_PORT = 5000;
const unsigned int PI_PORT    = 5001;

// ── Pin assignments ──────────────────────────────────────────
#define PIN_W5500_CS      10
#define PIN_W5500_RST      9
#define PIN_LED_GREEN      3   // Connected indicator
#define PIN_LED_RED        2   // Disconnected indicator
#define PIN_LED_HB         8   // Heartbeat blink
#define PIN_MOTOR_A_UP     4
#define PIN_MOTOR_A_DOWN   5
#define PIN_MOTOR_B_UP     6
#define PIN_MOTOR_B_DOWN   7

// ── Packet constants ─────────────────────────────────────────
#define MAGIC_CMD    0xAB
#define MAGIC_ACK    0xBA
#define TYPE_CMD     0x01
#define TYPE_HB      0x02
#define CMD_STOP     0x00
#define CMD_UP       0x01
#define CMD_DOWN     0x02
#define PKT_IN_LEN   6
#define PKT_OUT_LEN  5

// ── Timing ───────────────────────────────────────────────────
#define WATCHDOG_MS    600   // Stop motors + go red if silent this long
#define HB_BLINK_MS     60   // Heartbeat LED on duration

// ── State ────────────────────────────────────────────────────
EthernetUDP  udp;
unsigned long lastPacketMs = 0;
unsigned long hbLedOnMs    = 0;
bool          hbLedOn      = false;
bool          wasConnected = false;
uint8_t       motorA       = CMD_STOP;
uint8_t       motorB       = CMD_STOP;

// ── Helpers ──────────────────────────────────────────────────
uint8_t xorChecksum(uint8_t *buf, uint8_t len) {
  uint8_t cs = 0;
  for (uint8_t i = 0; i < len; i++) cs ^= buf[i];
  return cs;
}

void stopAllMotors() {
  motorA = CMD_STOP;
  motorB = CMD_STOP;
  digitalWrite(PIN_MOTOR_A_UP,   LOW);
  digitalWrite(PIN_MOTOR_A_DOWN, LOW);
  digitalWrite(PIN_MOTOR_B_UP,   LOW);
  digitalWrite(PIN_MOTOR_B_DOWN, LOW);
}

void applyMotor(uint8_t pinUp, uint8_t pinDown, uint8_t cmd) {
  digitalWrite(pinUp,   (cmd == CMD_UP)   ? HIGH : LOW);
  digitalWrite(pinDown, (cmd == CMD_DOWN) ? HIGH : LOW);
}

void setConnected(bool connected) {
  if (connected == wasConnected) return;   // No change, skip
  wasConnected = connected;
  digitalWrite(PIN_LED_GREEN, connected ? HIGH : LOW);
  digitalWrite(PIN_LED_RED,   connected ? LOW  : HIGH);
  Serial.println(connected ? F("STATUS: CONNECTED") : F("STATUS: DISCONNECTED"));
}

void triggerHbLed() {
  digitalWrite(PIN_LED_HB, HIGH);
  hbLedOn   = true;
  hbLedOnMs = millis();
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

// ── Setup ─────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Serial.println(F("Motor Control Node v2.0 starting..."));

  // Output pins
  pinMode(PIN_MOTOR_A_UP,   OUTPUT);
  pinMode(PIN_MOTOR_A_DOWN, OUTPUT);
  pinMode(PIN_MOTOR_B_UP,   OUTPUT);
  pinMode(PIN_MOTOR_B_DOWN, OUTPUT);
  pinMode(PIN_LED_GREEN,    OUTPUT);
  pinMode(PIN_LED_RED,      OUTPUT);
  pinMode(PIN_LED_HB,       OUTPUT);

  // Start in disconnected state
  stopAllMotors();
  digitalWrite(PIN_LED_GREEN, LOW);
  digitalWrite(PIN_LED_RED,   HIGH);
  digitalWrite(PIN_LED_HB,    LOW);

  // Reset W5500
  pinMode(PIN_W5500_RST, OUTPUT);
  digitalWrite(PIN_W5500_RST, LOW);
  delay(80);
  digitalWrite(PIN_W5500_RST, HIGH);
  delay(300);

  Ethernet.init(PIN_W5500_CS);
  Ethernet.begin(mac, localIP);
  delay(500);

  Serial.print(F("IP: "));
  Serial.println(Ethernet.localIP());
  Serial.print(F("Listening on port: "));
  Serial.println(LOCAL_PORT);

  udp.begin(LOCAL_PORT);
  lastPacketMs = millis();
}

// ── Loop ──────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // ── Watchdog check ──
  bool connected = (now - lastPacketMs) < WATCHDOG_MS;
  if (!connected) stopAllMotors();
  setConnected(connected);

  // ── Heartbeat LED off after blink ──
  if (hbLedOn && (now - hbLedOnMs > HB_BLINK_MS)) {
    hbLedOn = false;
    digitalWrite(PIN_LED_HB, LOW);
  }

  // ── Receive packet ──
  int pktSize = udp.parsePacket();
  if (pktSize < PKT_IN_LEN) return;

  uint8_t buf[PKT_IN_LEN];
  udp.read(buf, PKT_IN_LEN);

  // Validate magic byte
  if (buf[0] != MAGIC_CMD) return;

  // Validate checksum
  if (xorChecksum(buf, PKT_IN_LEN - 1) != buf[PKT_IN_LEN - 1]) {
    Serial.println(F("Bad checksum — packet dropped"));
    return;
  }

  uint8_t seq  = buf[1];
  uint8_t type = buf[2];

  lastPacketMs = now;
  triggerHbLed();

  if (type == TYPE_HB) {
    sendAck(seq);
    return;
  }

  if (type == TYPE_CMD) {
    uint8_t cmdA = buf[3];
    uint8_t cmdB = buf[4];
    if (cmdA > CMD_DOWN || cmdB > CMD_DOWN) return;

    motorA = cmdA;
    motorB = cmdB;
    applyMotor(PIN_MOTOR_A_UP, PIN_MOTOR_A_DOWN, motorA);
    applyMotor(PIN_MOTOR_B_UP, PIN_MOTOR_B_DOWN, motorB);

    Serial.print(F("CMD  A="));
    Serial.print(motorA);
    Serial.print(F("  B="));
    Serial.println(motorB);

    sendAck(seq);
  }
}
