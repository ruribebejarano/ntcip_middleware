package pe.pucp.ntcip.obu.obu

import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

data class ResultadoSntp(val offsetMs: Long, val rttMs: Long, val servidor: String)

/**
 * Cliente SNTP mínimo (UDP, puerto 123) que NO toca el reloj del sistema:
 * solo mide el offset probable y el RTT contra un servidor NTP público,
 * en el mismo espíritu que `chronyc tracking` en la laptop/Pi (ver
 * docs/ARRANQUE_BROKER_LAPTOP.md), pero como una medición puntual al
 * inicio y al fin de cada misión (ver ObuSessionService), no disciplina
 * continua -- ver app_obu/README.md, sección "Reloj y eventos", para la
 * limitación que esto deja frente a las métricas de la Pi/laptop.
 *
 * Fórmula estándar SNTP (RFC 5905, simplificada a un solo intercambio):
 *   offset = ((T2-T1)+(T3-T4)) / 2 ;  rtt = (T4-T1)-(T3-T2)
 * T1 = envío local, T2 = recepción en el servidor, T3 = envío del
 * servidor, T4 = recepción local (los cuatro con el reloj de quien los
 * midió -- T1/T4 con el reloj SIN corregir de la tablet, que es
 * justamente lo que se quiere acotar).
 */
object SntpCliente {
    private const val SERVIDOR_DEFECTO = "time.cloudflare.com"
    private const val PUERTO_NTP = 123
    private const val EPOCA_NTP_A_UNIX_S = 2_208_988_800L // 1900-01-01 -> 1970-01-01
    private const val TIMEOUT_MS = 2000

    fun consultar(servidor: String = SERVIDOR_DEFECTO): ResultadoSntp? = runCatching {
        val direccion = InetAddress.getByName(servidor)
        val paqueteTx = ByteArray(48)
        paqueteTx[0] = 0x23 // LI=0, VN=4, Mode=3 (cliente)

        DatagramSocket().use { socket ->
            socket.soTimeout = TIMEOUT_MS
            val t1 = System.currentTimeMillis()
            escribirMarcaTiempo(paqueteTx, 40, t1) // Transmit Timestamp propio

            socket.send(DatagramPacket(paqueteTx, paqueteTx.size, direccion, PUERTO_NTP))

            val bufferRx = ByteArray(48)
            socket.receive(DatagramPacket(bufferRx, bufferRx.size))
            val t4 = System.currentTimeMillis()

            val t2 = leerMarcaTiempo(bufferRx, 32) // Receive Timestamp del servidor
            val t3 = leerMarcaTiempo(bufferRx, 40) // Transmit Timestamp del servidor

            ResultadoSntp(
                offsetMs = ((t2 - t1) + (t3 - t4)) / 2,
                rttMs = (t4 - t1) - (t3 - t2),
                servidor = servidor,
            )
        }
    }.getOrNull()

    private fun escribirMarcaTiempo(buffer: ByteArray, offset: Int, epochMs: Long) {
        val segundosNtp = epochMs / 1000 + EPOCA_NTP_A_UNIX_S
        val fraccion = ((epochMs % 1000) * 0x100000000L) / 1000
        for (i in 0 until 4) buffer[offset + i] = (segundosNtp shr (24 - 8 * i)).toByte()
        for (i in 0 until 4) buffer[offset + 4 + i] = (fraccion shr (24 - 8 * i)).toByte()
    }

    private fun leerMarcaTiempo(buffer: ByteArray, offset: Int): Long {
        var segundosNtp = 0L
        for (i in 0 until 4) segundosNtp = (segundosNtp shl 8) or (buffer[offset + i].toLong() and 0xFF)
        var fraccion = 0L
        for (i in 0 until 4) fraccion = (fraccion shl 8) or (buffer[offset + 4 + i].toLong() and 0xFF)
        val segundosUnix = segundosNtp - EPOCA_NTP_A_UNIX_S
        val ms = (fraccion * 1000) / 0x100000000L
        return segundosUnix * 1000 + ms
    }
}
