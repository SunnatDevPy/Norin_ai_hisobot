package uz.norinai.norin_ai_app

import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.net.Uri
import android.os.Build
import android.os.CancellationSignal
import android.provider.Settings
import androidx.core.content.FileProvider
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : FlutterActivity() {
    private val channelName = "uz.norinai.norin_ai_app/installer"
    private var pendingApkPath: String? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "installApk" -> {
                        val path = call.argument<String>("path")
                        if (path.isNullOrBlank()) {
                            result.error("INVALID_PATH", "APK fayl manzili bo'sh", null)
                            return@setMethodCallHandler
                        }
                        val file = File(path)
                        if (!file.exists()) {
                            result.error("NOT_FOUND", "APK fayl topilmadi: $path", null)
                            return@setMethodCallHandler
                        }
                        try {
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
                                !packageManager.canRequestPackageInstalls()
                            ) {
                                pendingApkPath = path
                                val permIntent = Intent(
                                    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                    Uri.parse("package:$packageName")
                                ).apply {
                                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                }
                                startActivity(permIntent)
                                result.success("PERMISSION_REQUESTED")
                            } else {
                                launchPackageInstaller(file)
                                result.success("INSTALLER_LAUNCHED")
                            }
                        } catch (e: Exception) {
                            result.error("INSTALL_ERROR", e.localizedMessage ?: e.toString(), null)
                        }
                    }

                    "openExternalUrl" -> {
                        val url = call.argument<String>("url")
                        if (url.isNullOrBlank()) {
                            result.success(false)
                            return@setMethodCallHandler
                        }
                        try {
                            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
                                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            }
                            startActivity(intent)
                            result.success(true)
                        } catch (_: Exception) {
                            result.success(false)
                        }
                    }

                    "canAuthenticateBiometric" -> {
                        result.success(canAuthenticateBiometric())
                    }

                    "authenticateBiometric" -> {
                        val title = call.argument<String>("title") ?: "Norin AI Himoyasi"
                        val subtitle = call.argument<String>("subtitle") ?: "Barmoq izi orqali tasdiqlang"
                        val cancelText = call.argument<String>("cancel") ?: "Bekor qilish"
                        authenticateBiometric(title, subtitle, cancelText, result)
                    }

                    else -> result.notImplemented()
                }
            }
    }

    private fun canAuthenticateBiometric(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
            return false
        }
        val kg = getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager
        if (kg?.isKeyguardSecure != true) {
            return false
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val bm = getSystemService(Context.BIOMETRIC_SERVICE) as? BiometricManager
            if (bm != null) {
                val res = bm.canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_WEAK)
                return res == BiometricManager.BIOMETRIC_SUCCESS
            }
        }
        return packageManager.hasSystemFeature(PackageManager.FEATURE_FINGERPRINT)
    }

    private fun authenticateBiometric(
        title: String,
        subtitle: String,
        cancelText: String,
        result: MethodChannel.Result
    ) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
            result.success(false)
            return
        }
        val replied = AtomicBoolean(false)
        fun finish(ok: Boolean) {
            if (replied.compareAndSet(false, true)) {
                runOnUiThread { result.success(ok) }
            }
        }

        try {
            val prompt = BiometricPrompt.Builder(this)
                .setTitle(title)
                .setSubtitle(subtitle)
                .setNegativeButton(cancelText, mainExecutor) { _, _ -> finish(false) }
                .build()

            val signal = CancellationSignal()
            prompt.authenticate(
                signal,
                mainExecutor,
                object : BiometricPrompt.AuthenticationCallback() {
                    override fun onAuthenticationSucceeded(authResult: BiometricPrompt.AuthenticationResult?) {
                        finish(true)
                    }

                    override fun onAuthenticationError(errorCode: Int, errString: CharSequence?) {
                        finish(false)
                    }

                    override fun onAuthenticationFailed() {
                        // Android keeps prompt open for next finger attempt until error/cancel
                    }
                }
            )
        } catch (_: Exception) {
            finish(false)
        }
    }

    override fun onResume() {
        super.onResume()
        val path = pendingApkPath
        if (!path.isNullOrBlank() &&
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            packageManager.canRequestPackageInstalls()
        ) {
            pendingApkPath = null
            val file = File(path)
            if (file.exists()) {
                try {
                    launchPackageInstaller(file)
                } catch (_: Exception) {
                }
            }
        }
    }

    private fun launchPackageInstaller(file: File) {
        val uri: Uri = FileProvider.getUriForFile(
            this,
            "$packageName.apkprovider",
            file
        )
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        startActivity(intent)
    }
}
