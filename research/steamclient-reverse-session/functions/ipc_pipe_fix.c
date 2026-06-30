/*
 * IPC Pipe Fix Analysis — Can We Fix the IPC Pipe?
 *
 * Binary: ~/.steam/debian-installation/ubuntu12_32/steamclient.so (32-bit, 49MB)
 * Status: DETERMINED (IPC pipe is NOT the solution)
 *
 * EXECUTIVE SUMMARY
 * =================
 * The IPC pipe "hiddevicepipesteam" is used by CGetControllerInfoWorkItem
 * to read controller details from the SDL HID daemon. However, this is a
 * DIFFERENT data path from the identity slot population.
 *
 * The IPC pipe populates ControllerDetails_tE (at controller+0x1070+id*0x54),
 * NOT the identity slot (at controller+slot*0xe8+0x200).
 *
 * The zombie check reads from the identity slot, NOT from ControllerDetails.
 * So fixing the IPC pipe would NOT fix the zombie disconnect.
 *
 * THE TWO DATA STRUCTURES
 * ========================
 *
 * 1. ControllerDetails_tE (stride 0x54)
 *    Location: controller + 0x1070 + id * 0x54
 *    Written by: QueueFetchingControllerDetails (0x1092820)
 *    Ready flag: controller+0x3c = 1
 *    Used by: EYldWaitForControllerDetails (blocks registration)
 *    Populated by: CallerOfQueueFetchingControllerDetails (0x10b2ca0)
 *                  reads from controller+0x84..0xd4
 *
 * 2. Identity Slot (stride 0xe8)
 *    Location: controller + slot * 0xe8 + 0x1f8
 *    Written by: Feature report response processing code
 *    Ready flag: slot+0x200 (first byte of unique_id) != 0
 *    Used by: GetControllerInfo (0x1070620) — zombie check
 *    Populated by: Feature report handshake (GET_ATTRIBUTES, GET_SERIAL, 0xf2)
 *
 * THE IPC PIPE
 * ============
 *
 * The IPC pipe "hiddevicepipesteam" is used by:
 *   CGetControllerInfoWorkItem::RunFunc (0x10xxxx)
 *
 * Flow:
 *   1. Steam opens the pipe "hiddevicepipesteam"
 *   2. CGetControllerInfoWorkItem reads from the pipe
 *   3. The pipe contains protobuf-encoded controller info
 *   4. Steam parses the protobuf and stores data in ControllerDetails
 *   5. QueueFetchingControllerDetails is called with the parsed data
 *   6. ControllerDetails ready_flag is set to 1
 *
 * The IPC pipe data goes to ControllerDetails, NOT the identity slot.
 *
 * WHY THE IPC PIPE DOESN'T HELP
 * ==============================
 *
 * The zombie check at 0x1070620 reads from the identity slot:
 *   0x107088c: cmp byte [rax+0x200], 0
 *
 * This reads from controller + slot*0xe8 + 0x200, which is the
 * identity slot's unique_id field.
 *
 * The IPC pipe populates ControllerDetails, which is at a DIFFERENT
 * location: controller + 0x1070 + id * 0x54.
 *
 * These are two completely separate data structures at different
 * memory addresses. Fixing one does not affect the other.
 *
 * THE CORRELATION
 * ===============
 *
 * The two data structures are related but independent:
 *
 * - ControllerDetails is used by the REGISTRATION flow
 *   (BYieldingRegisterSteamController → EYldWaitForControllerDetails)
 *
 * - Identity Slot is used by the ZOMBIE CHECK flow
 *   (slot iterator → GetControllerInfo → zombie disconnect)
 *
 * Both must be populated for the controller to work, but they are
 * populated by DIFFERENT code paths:
 *
 * - ControllerDetails: populated by QueueFetchingControllerDetails
 *   which reads from controller+0x84..0xd4
 *
 * - Identity Slot: populated by feature report response processing
 *   which reads from Feature Report 0x00 responses
 *
 * WHAT THE IPC PIPE DOES
 * =======================
 *
 * From the analysis of CGetControllerInfoWorkItem:
 *
 * 1. The pipe contains protobuf messages with controller info
 * 2. The message format is CHIDMessageToRemote.DeviceRead
 * 3. The response is a RequestResponse with a data field
 * 4. The data field contains controller details (product ID, firmware, etc.)
 * 5. This data is stored in the ControllerDetails array
 *
 * The IPC pipe is used for COMMUNICATION between the SDL HID daemon
 * and the Steam client. It's NOT used for the feature report handshake.
 *
 * CONCLUSION
 * ===========
 *
 * The IPC pipe cannot be used to fix the zombie disconnect because:
 * 1. It populates ControllerDetails, not the identity slot
 * 2. The zombie check reads from the identity slot
 * 3. These are different data structures at different addresses
 *
 * The only way to fix the zombie disconnect is to populate the identity
 * slot at controller+slot*0xe8+0x200 with a non-zero serial number.
 * This requires the feature report handshake to complete, which requires
 * BlueZ to send ATT Read Requests for Feature Reports.
 *
 * FUNCTION REFERENCES
 * ===================
 * 0x1092820: QueueFetchingControllerDetails (writes ControllerDetails)
 * 0x10b2ca0: CallerOfQueueFetchingControllerDetails (reads controller+0x84..0xd4)
 * 0x1070620: GetControllerInfo (zombie check, reads identity slot)
 * 0x10d4e6c: FeatureReportStateMachine (processes FR 0x00 responses)
 * 0x105c7f0: InitializeSlotDefaults (clears identity slot)
 * 0x105ca80: CopyIdentityData (requires slot+0x200 != 0)
 */

⚠️ DISCLAIMER: WRONG BINARY ANALYZED

All analysis in this file was performed on the WRONG binary:
  ~/.steam/debian-installation/ubuntu12_32/steamclient.so (49MB, 32-bit) [CORRECT]

Steam actually loads:
  ~/.steam/debian-installation/ubuntu12_32/steamclient.so (49MB, 32-bit i386)

ALL ADDRESSES, FUNCTION OFFSETS, AND DISASSEMBLY ARE WRONG for the running process.
The conceptual findings (gate mechanism, YieldingRunTestProgram, job system) likely
apply to both binaries, but every specific address must be re-derived from the
32-bit binary or verified via GDB on the running process.

Verified: 2026-06-29
- Steam process: ELF 32-bit LSB pie executable (i386)
- steamclient.so loaded: ubuntu12_32/steamclient.so
- YieldingRunTestProgram string: 0x00bfc7e3 (32-bit) vs 0x00d6d17b (64-bit)

