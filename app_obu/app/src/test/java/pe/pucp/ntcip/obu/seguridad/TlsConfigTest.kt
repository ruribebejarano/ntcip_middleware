package pe.pucp.ntcip.obu.seguridad

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Prueba de la parte de B4 que no necesita Android ni un broker real: que
 * TlsConfig parsea los tres PEM de scripts/seguridad/generar_ca.py (llave
 * en PKCS#8, ver la nota en ese script) y construye un KeyManagerFactory/
 * TrustManagerFactory sin excepciones. Fixture generada con openssl para
 * esta prueba (CA y certificado de cliente CN=ses-test01), no viene de
 * deploy/pki/ (gitignored, nunca se commitea una llave real).
 */
class TlsConfigTest {

    private val caCertPem = """
        -----BEGIN CERTIFICATE-----
        MIIDBTCCAe2gAwIBAgIUSx9Yyy+359RexAm6Xe+hdILRFMIwDQYJKoZIhvcNAQEL
        BQAwEjEQMA4GA1UEAwwHQ0EtdGVzdDAeFw0yNjExMDIwMzUxNDJaFw0zNjEwMzAw
        MzUxNDJaMBIxEDAOBgNVBAMMB0NBLXRlc3QwggEiMA0GCSqGSIb3DQEBAQUAA4IB
        DwAwggEKAoIBAQDAAPj7J2Oa0Qv44FF6jp3qLSE7GDp+76CntTXiVrl1++iDOODC
        hahxNv9Z4ZU5Boba3EPyIJg6IKbhz1MrDuvS8q9MqK2WXVNn4loFnPdNZhJiahf1
        OpeWiQOt4PRbn8hkIV3Fy6DDT6c4Bd1Xspok4sMgY59IxieTumYucyqU/8Lof3ph
        V57dN0vZifL3HgPPTBADH7LH8eIUKbiS9DCgl4YJ8jY9J6A4RSUh4+MAYC/H5gXI
        6T6p2Qe787sIL0Ef9T50c2eW+CavNGwdKu3DBe3INRvCxneVGGESjNA1SiAlwYko
        gRSsCxnKwsXr5PJ5lqvyPwxFlZfi3TH6wYWdAgMBAAGjUzBRMB0GA1UdDgQWBBQ+
        Q4nSPnDiL5rFZudLQKuYVdfEWzAfBgNVHSMEGDAWgBQ+Q4nSPnDiL5rFZudLQKuY
        VdfEWzAPBgNVHRMBAf8EBTADAQH/MA0GCSqGSIb3DQEBCwUAA4IBAQBZVoADHnTI
        fwuTbPGdzYp48QdlPIb9UFPJeX7lPvuQRXJ14O4T/B8vKf7Kk0pAsVtuZLODZ9iA
        arDBJ14OH0lX0CUnERUMEOG4tRuf/j7VBwumXIObiOWjK0m3oB4BtEL7JjN+Ka0O
        lWtN1FOokR0rqgD3SdwPdai19ui+IRbKmUG/sG8CCxmUyPqNN7+DspYqvRyrxIg8
        52yjyBXtaf3hJK5T4BgGzQuoKfgA/VE+kaCfG/UwzBFbCzrHA9NbdNwJc3KwYU55
        xLwFNtR0SPhSc2rgeFbeyvxq/peSrc1Rca369dYc6lwBkdf16K6uKAqK9oQw4xl8
        KfhdJQU4y0cu
        -----END CERTIFICATE-----
    """.trimIndent().toByteArray()

    private val clientCertPem = """
        -----BEGIN CERTIFICATE-----
        MIIC9zCCAd+gAwIBAgIUAMXYNI7/HB+7/VnXjR77LJ+sJHowDQYJKoZIhvcNAQEL
        BQAwEjEQMA4GA1UEAwwHQ0EtdGVzdDAeFw0yNjExMDIwMzUxNDNaFw0yOTAyMDQw
        MzUxNDNaMBUxEzARBgNVBAMMCnNlcy10ZXN0MDEwggEiMA0GCSqGSIb3DQEBAQUA
        A4IBDwAwggEKAoIBAQCzzTRy7/eV4Viin7Tle75GHeFhXgexwfKaP46OEWuZkqq3
        +S5qohZK4WyTWZ1HnrudtICm84qljsODPVJmTeElmYDgmhsUAeAZLK/Smcq+kGqD
        GkuIp1JGVUW3fE+Y7dvMlLc8xTYMtUirse6iG0yC01ANIA8h+NQ5JnOhy+jwDLHc
        YaYzghXCHtAuP8+HGzmSUx+SrVHschWayOTZtppIghzf42NdRW6Z8knk7Q9LpHeh
        TpWci/ELkCltIn5/uCPQIckBpa9bivzfj2baZpULa2q8GCvRZsy7TUUWwfCosvRo
        R1s8Hcs5ZyRI2CIvAiJQu2XleUzEzrKhtq1w3zazAgMBAAGjQjBAMB0GA1UdDgQW
        BBQ7bCbIk/C2zKg357PnslkgJOj34jAfBgNVHSMEGDAWgBQ+Q4nSPnDiL5rFZudL
        QKuYVdfEWzANBgkqhkiG9w0BAQsFAAOCAQEAZK8KLJA6sLnnA/abIyGsW2hwki8C
        5RmnM+PLR4KAeOoSrIoPlAhXRwbwNpj/arEUWJ3xUkWXmXWlC8Y+tgk3VazsY36z
        InF8CTqe9Vn1sXqDR7fmvXWtjZISvUt+dNqFMpYRDXZvvrZ/AkEITX4yh0Uso2EG
        SWrTBasaXi9XHg7Egsk1yedCug5T84Glq87pGYp+pi7N0Hji5Bv5LTpoAHKErP5i
        j+RnNW7weTj7Q+4M9ovqppX6h98fOpJSqSfAul6VjwF5OwSkCe0wZ8Iy1rvXpeBF
        7XJRGoNGQwx/ctQyn3P0yNc4vo4Ncei3pg+T8CY7MvI/Tn2g1pozi1qZWw==
        -----END CERTIFICATE-----
    """.trimIndent().toByteArray()

    private val clientKeyPem = """
        -----BEGIN PRIVATE KEY-----
        MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQCzzTRy7/eV4Vii
        n7Tle75GHeFhXgexwfKaP46OEWuZkqq3+S5qohZK4WyTWZ1HnrudtICm84qljsOD
        PVJmTeElmYDgmhsUAeAZLK/Smcq+kGqDGkuIp1JGVUW3fE+Y7dvMlLc8xTYMtUir
        se6iG0yC01ANIA8h+NQ5JnOhy+jwDLHcYaYzghXCHtAuP8+HGzmSUx+SrVHschWa
        yOTZtppIghzf42NdRW6Z8knk7Q9LpHehTpWci/ELkCltIn5/uCPQIckBpa9bivzf
        j2baZpULa2q8GCvRZsy7TUUWwfCosvRoR1s8Hcs5ZyRI2CIvAiJQu2XleUzEzrKh
        tq1w3zazAgMBAAECggEADNiWF7l8sfEAuSsPQe9pCm9ra952Tu/xb63SIeUCurKC
        Of9hSUMSs/+ObKn+v7WKkrDpGYSAR7spzYBIboC/8O9vsscFNOpmuBsQ5iC7czQJ
        jXEH1oKbMTqPGZXrG0ewktmejIahNEqQykY91h0nMUL8ZC5XMRvVuyORKA0pM6/w
        dINoWVGyLvFjujShuay3JbooZNe6eD6uPS7kLTFA8uHg7LyStyTe1FgurTCvuBJZ
        2NMYQVQPLCb7kf6bsjTypeW/KEyrRgtOkzMZ2bjWm3jEMuaodVSUJHcYzs2eXc08
        QiyUaX+NyAACxSOKxogZkg/CZIiQdHFpgrM6a6E4mQKBgQDkTjuTedS3Btp7ihPE
        pxtTHGHbj5Q/5/128sAh4YmqBLiDi3Y+fq9bEw7N+3hBpIwrh1w0xhhhveiZ/Bwj
        Ld5biOgT+FPD8kxHdtKySEuHYSlZ+Qi2Z1c60J4V6dLJg13u7CAlQhYEC7a8hTmE
        R9Vuvrl1Wz+q/XgjahMrMbvkxwKBgQDJnLxg3mpZZKtH41Y8bdEp/q7B+uPkcHbR
        Eqiphf5ZUmBmNnl1Eqh8CGji7t4JZ+zDaGNrsdI1doq53pS5tvYvILIFxMAli3mv
        kVvuK4AXJKIzHXrouLdDtn6QhKl4pCRXJRp57oOr3baF6uUF2gqiW4jeD/7bxMtA
        79SCCSPatQKBgFD5HlA0CanQmHTwiApbammTy3Ff/yibU154woRBxd2zRu4A7LNF
        o1Qd8kZERmahwcU+gQmGqOchv/m9XQ1tG0xDxmwuyybYLQ27qwbodUFSyKPMm7Z1
        +I43p5oGEGjAWvR+cvhD9CMDNJCwf7HW+HAK3SQudOpkc9O7r4jGXunJAoGAXvTe
        WLWI22+pqGMvk6iZcjEM+DoFqes6WwBxxd5hTIqa8qlHjVdrWXfQhsnAdCepgOOi
        p++JtTqO3joyTEIbM1kv372qTkSh3IoXBVchrkTHzFFfOUr+rfq/I6wH8dVFdHH6
        RWGMTJ9RP0PB+H6YsZ1xGj3oaHQI0x3iNhi99V0CgYANZ7D4geRlSqqR3edVVHyn
        KzqHuWNXNmwzeDSy+GiF6NNeReQlQkLNlZmhc4A+0/xLYGq82HHjNPbW57yKCszq
        sl7W34tp3aUZxZXdxjodL9a6zqpU8MkouSK/a09uq12+0D3OM4dXBqFei21NUmL3
        W++RZ0neZFFXvzLoXX3/JA==
        -----END PRIVATE KEY-----
    """.trimIndent().toByteArray()

    private fun tlsConfig() = TlsConfig(caCertPem, clientCertPem, clientKeyPem)

    @Test
    fun `keyManagerFactory parsea el certificado y la llave PKCS8 sin excepcion`() {
        val kmf = tlsConfig().keyManagerFactory()
        assertTrue(kmf.keyManagers.isNotEmpty())
    }

    @Test
    fun `trustManagerFactory parsea la CA sin excepcion`() {
        val tmf = tlsConfig().trustManagerFactory()
        assertTrue(tmf.trustManagers.isNotEmpty())
    }

    @Test
    fun `commonNameCliente extrae el CN del certificado (item 2b, obu_id fijo por dispositivo)`() {
        assertEquals("ses-test01", tlsConfig().commonNameCliente())
    }

    @Test
    fun `el certificado de cliente tiene el CN esperado (obu_id de prueba)`() {
        // El CN debe ser EXACTAMENTE el obu_id (docs/CONTRATO_OBU.md §1,
        // ACL por use_identity_as_username) -- esta fixture se emitio con
        // CN=ses-test01.
        val cert = java.security.cert.CertificateFactory.getInstance("X.509")
            .generateCertificate(clientCertPem.inputStream())
        val dn = (cert as java.security.cert.X509Certificate).subjectX500Principal.name
        assertEquals("CN=ses-test01", dn)
    }
}
