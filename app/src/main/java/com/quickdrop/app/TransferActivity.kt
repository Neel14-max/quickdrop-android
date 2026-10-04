package com.quickdrop.app

import android.content.ContentValues
import android.net.Uri
import android.net.http.SslError
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.view.WindowManager
import android.webkit.*
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import java.io.IOException
import java.net.URL
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/** Shows the laptop's transfer page. The TLS certificate is PINNED to the fingerprint from the QR code. */
class TransferActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var fp: String
    private lateinit var host: String
    private var chooser: ValueCallback<Array<Uri>>? = null

    private val picker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        chooser?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(res.resultCode, res.data))
        chooser = null
    }

    private fun sha256(b: ByteArray) =
        MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val url = intent.getStringExtra("url") ?: return finish()
        val u = Uri.parse(url)
        fp = (u.getQueryParameter("fp") ?: "").lowercase()
        host = u.host ?: return finish()

        web = WebView(this)
        setContentView(web)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
        }
        CookieManager.getInstance().setAcceptCookie(true)

        web.webViewClient = object : WebViewClient() {
            override fun onReceivedSslError(v: WebView, h: SslErrorHandler, e: SslError) {
                val der = e.certificate.x509Certificate?.encoded
                if (der != null && sha256(der) == fp) h.proceed() else {
                    h.cancel()
                    Toast.makeText(this@TransferActivity, "Security check failed: wrong device", Toast.LENGTH_LONG).show()
                }
            }
            override fun shouldOverrideUrlLoading(v: WebView, r: WebResourceRequest) =
                r.url.host != host   // never navigate away from the laptop
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(w: WebView, cb: ValueCallback<Array<Uri>>, p: FileChooserParams): Boolean {
                chooser?.onReceiveValue(null)
                chooser = cb
                return try { picker.launch(p.createIntent()); true }
                catch (e: Exception) { chooser = null; cb.onReceiveValue(null); false }
            }
        }
        web.setDownloadListener { dlUrl, _, _, _, _ -> download(dlUrl) }
        web.loadUrl(url)
    }

    private fun toast(m: String) = runOnUiThread { Toast.makeText(this, m, Toast.LENGTH_LONG).show() }

    private fun pinnedContext(): SSLContext {
        val tm = object : X509TrustManager {
            override fun checkClientTrusted(c: Array<X509Certificate>, a: String) {}
            override fun checkServerTrusted(c: Array<X509Certificate>, a: String) {
                if (sha256(c[0].encoded) != fp) throw CertificateException("Certificate mismatch")
            }
            override fun getAcceptedIssuers() = arrayOf<X509Certificate>()
        }
        return SSLContext.getInstance("TLS").apply { init(null, arrayOf(tm), null) }
    }

    /** Streams the file straight into Downloads/QuickDrop (no RAM buffering, no extra permission). */
    private fun download(url: String) {
        val name = Uri.parse(url).lastPathSegment ?: "file"
        toast("Downloading $name ...")
        Thread {
            try {
                val conn = (URL(url).openConnection() as HttpsURLConnection).apply {
                    sslSocketFactory = pinnedContext().socketFactory
                    setHostnameVerifier { _, _ -> true }   // safe: certificate is pinned
                    setRequestProperty("Cookie", CookieManager.getInstance().getCookie(url) ?: "")
                    connectTimeout = 10000
                    readTimeout = 30000
                }
                if (conn.responseCode != 200) throw IOException("HTTP ${conn.responseCode}")
                val ext = name.substringAfterLast('.', "").lowercase()
                val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "application/octet-stream"
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, name)
                    put(MediaStore.Downloads.MIME_TYPE, mime)
                    put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/QuickDrop")
                    put(MediaStore.Downloads.IS_PENDING, 1)
                }
                val dest = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: throw IOException("Cannot create file")
                contentResolver.openOutputStream(dest)!!.use { out ->
                    conn.inputStream.use { it.copyTo(out, 1 shl 20) }
                }
                values.clear()
                values.put(MediaStore.Downloads.IS_PENDING, 0)
                contentResolver.update(dest, values, null, null)
                toast("Saved to Downloads/QuickDrop: $name")
            } catch (e: Exception) {
                toast("Download failed: ${e.message}")
            }
        }.start()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }
}
