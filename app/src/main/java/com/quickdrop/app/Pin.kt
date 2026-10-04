package com.quickdrop.app

import android.content.Context
import java.net.Inet4Address
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket
import java.net.URL
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicReference
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/** TLS connections whose certificate is pinned to the fingerprint learned from the QR code. */
object Pin {
    fun sha256(b: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }

    fun context(fp: String): SSLContext {
        val tm = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                if (sha256(chain[0].encoded) != fp) throw CertificateException("Certificate mismatch")
            }
            override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
        }
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf<TrustManager>(tm), null)
        return ctx
    }

    fun open(url: String, fp: String, cookie: String?, connectMs: Int = 10000, readMs: Int = 30000): HttpsURLConnection {
        val c = URL(url).openConnection() as HttpsURLConnection
        c.sslSocketFactory = context(fp).socketFactory
        c.hostnameVerifier = HostnameVerifier { _, _ -> true }   // safe: certificate is pinned
        if (!cookie.isNullOrEmpty()) c.setRequestProperty("Cookie", cookie)
        c.connectTimeout = connectMs
        c.readTimeout = readMs
        return c
    }
}

/** Remembers the paired laptop so the QR code is needed only once. */
object Store {
    private fun p(c: Context) = c.getSharedPreferences("quickdrop", Context.MODE_PRIVATE)
    fun base(c: Context): String? = p(c).getString("base", null)
    fun fp(c: Context): String? = p(c).getString("fp", null)
    fun cookie(c: Context): String? = p(c).getString("cookie", null)
    fun save(c: Context, base: String, fp: String, cookie: String?) {
        p(c).edit().putString("base", base).putString("fp", fp).putString("cookie", cookie).apply()
    }
    fun clear(c: Context) { p(c).edit().clear().apply() }
}

/** Finds the paired laptop on the hotspot network (its IP can change between sessions). */
object Finder {
    const val PORT = 8443

    fun ping(base: String, fp: String): Boolean = try {
        Pin.open("$base/api/ping", fp, null, 1500, 1500).responseCode == 200
    } catch (e: Exception) {
        false
    }

    fun find(fp: String): String? {
        val prefixes = linkedSetOf<String>()
        try {
            val nis = NetworkInterface.getNetworkInterfaces()
            while (nis != null && nis.hasMoreElements()) {
                val ni = nis.nextElement()
                if (!ni.isUp || ni.isLoopback) continue
                for (ia in ni.interfaceAddresses) {
                    val a = ia.address
                    if (a is Inet4Address && a.isSiteLocalAddress) {
                        prefixes.add(a.hostAddress!!.substringBeforeLast('.'))
                    }
                }
            }
        } catch (e: Exception) {
        }
        val hosts = prefixes.flatMap { p -> (1..254).map { "$p.$it" } }
        if (hosts.isEmpty()) return null
        val found = AtomicReference<String?>(null)
        val pool = Executors.newFixedThreadPool(64)
        try {
            val tasks = hosts.map { h ->
                Callable<Unit> {
                    if (found.get() == null && probe(h, fp)) {
                        found.compareAndSet(null, h)
                    }
                    Unit
                }
            }
            pool.invokeAll(tasks)
        } finally {
            pool.shutdownNow()
        }
        return found.get()?.let { "https://$it:$PORT" }
    }

    private fun probe(host: String, fp: String): Boolean = try {
        Socket().use { it.connect(InetSocketAddress(host, PORT), 400) }
        ping("https://$host:$PORT", fp)
    } catch (e: Exception) {
        false
    }
}
