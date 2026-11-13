package com.redclaw.jolven_flutter.rompatcher

import java.nio.file.Files
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.zip.CRC32
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class RomPatchEngineTest {
    @Test fun appliesIpsToIndependentFile() {
        val original = Files.createTempFile("jolven-rom-", ".gba")
        val patch = Files.createTempFile("jolven-patch-", ".ips")
        val output = Files.createTempFile("jolven-output-", ".gba")
        try {
            val bytes = byteArrayOf(0, 0, 0, 0)
            Files.write(original, bytes)
            val ips = "PATCH".toByteArray() +
                byteArrayOf(0, 0, 1, 0, 1, 0x7f) +
                "EOF".toByteArray()
            Files.write(patch, ips)
            assertEquals(PatchFormat.IPS, RomPatchEngine.inspect(patch).format)
            RomPatchEngine.apply(original, patch, output)
            assertArrayEquals(bytes, Files.readAllBytes(original))
            assertArrayEquals(byteArrayOf(0, 0x7f, 0, 0), Files.readAllBytes(output))
        } finally {
            Files.deleteIfExists(original)
            Files.deleteIfExists(patch)
            Files.deleteIfExists(output)
        }
    }

    private fun crcLittleEndian(data: ByteArray): ByteArray {
        val crc = CRC32().also { it.update(data) }.value.toInt()
        return ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(crc).array()
    }

    @Test fun appliesUpsAndChecksInputAndTargetCrc() {
        val source = Files.createTempFile("jolven-ups-rom-", ".bin")
        val patch = Files.createTempFile("jolven-ups-patch-", ".ups")
        val output = Files.createTempFile("jolven-ups-out-", ".bin")
        val before = byteArrayOf(1, 2)
        val after = byteArrayOf(0x5b, 2)
        try {
            Files.write(source, before)
            // UPS little-endian varints: 2 = 0x82, skip 0 = 0x80.
            val body = "UPS1".toByteArray() + byteArrayOf(
                0x82.toByte(), 0x82.toByte(), 0x80.toByte(), 0x5a, 0
            ) + crcLittleEndian(before) + crcLittleEndian(after)
            Files.write(patch, body + crcLittleEndian(body))
            assertEquals(PatchFormat.UPS, RomPatchEngine.inspect(patch).format)
            RomPatchEngine.apply(source, patch, output, ApplyOptions(requireValidation = true))
            assertArrayEquals(before, Files.readAllBytes(source))
            assertArrayEquals(after, Files.readAllBytes(output))
        } finally {
            Files.deleteIfExists(source)
            Files.deleteIfExists(patch)
            Files.deleteIfExists(output)
        }
    }

    @Test fun appliesBpsTargetReadAndValidatesCrc() {
        val source = Files.createTempFile("jolven-bps-rom-", ".bin")
        val patch = Files.createTempFile("jolven-bps-patch-", ".bps")
        val output = Files.createTempFile("jolven-bps-out-", ".bin")
        val before = byteArrayOf(1, 2)
        val after = byteArrayOf(9, 10)
        try {
            Files.write(source, before)
            // BPS: source=2, target=2, metadata=0; action=target-read(2).
            val body = "BPS1".toByteArray() + byteArrayOf(
                0x82.toByte(), 0x82.toByte(), 0x80.toByte(),
                0x85.toByte(), 9, 10
            ) + crcLittleEndian(before) + crcLittleEndian(after)
            Files.write(patch, body + crcLittleEndian(body))
            assertEquals(PatchFormat.BPS, RomPatchEngine.inspect(patch).format)
            RomPatchEngine.apply(source, patch, output, ApplyOptions(requireValidation = true))
            assertArrayEquals(before, Files.readAllBytes(source))
            assertArrayEquals(after, Files.readAllBytes(output))
        } finally {
            Files.deleteIfExists(source)
            Files.deleteIfExists(patch)
            Files.deleteIfExists(output)
        }
    }

    @Test fun rejectsUnsupportedPatchMagic() {
        val patch = Files.createTempFile("jolven-bad-", ".bin")
        try {
            Files.write(patch, "THIS IS NOT A PATCH".toByteArray())
            assertThrows(IllegalStateException::class.java) {
                RomPatchEngine.inspect(patch)
            }
        } finally {
            Files.deleteIfExists(patch)
        }
    }
}
