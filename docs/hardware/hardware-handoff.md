# Pocket computer hardware: handoff (31 Oct 2026)

Main doc with the shopping list, links and wiring: https://claude.ai/artifact/QAD9JDTUvJHv9fZqXvWDdL
Next steps, other boards and add-ons: https://claude.ai/artifact/UgNt2oEdvyDaBiR3sVfm47

## Final build (about €200 to €215; solar panel deferred, about €25 to €35 if added later)
- Board: Raspberry Pi Zero 2 WH (sold out at Welectron, BerryBase, Kiwi, Kubii and Elektronica voor jou; stock alerts needed). Plan B: Pi 3 A+.
- Screen: Waveshare 3.5" RPi LCD (A), resistive touch, the only input (no keyboard).
- Storage: 128 GB high-endurance microSD (about €35 now), plus a second card as a backup copy.
- Power: Waveshare UPS HAT (C). It charges via MICRO-USB, so a waterproof panel USB-C socket (5.1 kΩ CC resistors) is wired to its 5 V input. 1000 mAh cell swapped for a 3000 to 5000 mAh 1S LiPo (JST-PH 2.0, check polarity). INA219 at 0x43; battery % is read from voltage. Bas later wants his own spot-welded 1S2P 18650 pack with a BMS on the same connector.
- Radio: Si4732 (FM/AM/SW/SSB, I2C 0x11, RST GPIO23), weather fax over a USB sound stick (10 µF cap + divider), 5 to 10 m wire antenna via a cable gland.
- SDR: Nooelec NESDR SMArt v5 as a bare board (RTL-SDR Blog V4 is discontinued), for airband, ADS-B, AIS, Meteor-M and marine VHF. 4-port micro-USB OTG hub (BerryBase).
- Sensors: BME280 (0x76, behind an ePTFE vent), ATGM336H GPS (/dev/serial0), ICM-42688-P (0x69, AD0 high; recommended over the MPU-6050 for the inertial heading and GPS spoof checks, about EUR 12, same wiring; MPU-6050 still works), QMC5883L (0x0D), DS3231 RTC (0x68).
- Audio: PAM8403 with L+R inputs joined; Si4732 and sound stick each fed in through 10 kΩ; 2 thin 40 mm speakers, one per channel, for redundancy. A spare PAM8403 is included (Bas said yes, 31 Oct 2026).
- Light: 1 W white LED (GPIO12) and red LED (GPIO13), each through a MOSFET with a 100 Ω gate resistor and 10 kΩ pull-down.
- Case: printed by Bas in ASA (or PETG), O-ring seal (NBR/EPDM), TPU bumpers, conformal coating (essential at sea), about 110 × 85 × 45 mm, 250 to 350 g.
- Dropped: CardKB keyboard, RDA5807M, local chatbot, floating pouch, PiSugar 3.

## Still open
- Solar panel: decided 31 Oct 2026 to leave it out for now; the waterproof USB-C socket already accepts a 10 W panel later.
- TinyTronics prices could not be read automatically; check them in the basket.
