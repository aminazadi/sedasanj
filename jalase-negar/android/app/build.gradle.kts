import java.util.Properties

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Release signing comes from a key.properties file kept outside the repository: either
// android/key.properties or the path in JALASE_KEY_PROPERTIES. Without it the release build falls
// back to the debug key; the update server rejects such an APK, so it can never be published.
val keyProperties = Properties().apply {
    val path = System.getenv("JALASE_KEY_PROPERTIES")
    val file = if (path.isNullOrBlank()) rootProject.file("key.properties") else File(path)
    if (file.isFile) file.inputStream().use { load(it) }
}

android {
    namespace = "app.jalasenegar.jalase_negar"
    compileSdk = 36
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_11.toString()
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "app.jalasenegar.jalase_negar"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    // One APK per channel. `direct` keeps the in-app updater; the store flavors (Bazaar, Myket)
    // drop it (see src/<flavor>/AndroidManifest.xml) because the store delivers updates.
    flavorDimensions += "store"
    productFlavors {
        create("direct") { dimension = "store" }
        create("bazaar") { dimension = "store" }
        create("myket") { dimension = "store" }
    }

    signingConfigs {
        if (keyProperties.getProperty("storeFile") != null) {
            create("release") {
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
                storeFile = file(keyProperties.getProperty("storeFile"))
                storePassword = keyProperties.getProperty("storePassword")
                keyAlias = keyProperties.getProperty("keyAlias")
                keyPassword = keyProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            // Keep development builds separate from the production-signed app.
            applicationIdSuffix = ".dev"
        }
        release {
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    packaging {
        resources {
            excludes += "**/libVkLayer_khronos_validation.so"
        }
        jniLibs {
            excludes += "**/x86_64/*.so"
            excludes += "**/armeabi-v7a/*.so"
        }
    }
}

dependencies {
    implementation("androidx.work:work-runtime:2.10.0")
    testImplementation("junit:junit:4.13.2")
}

flutter {
    source = "../.."
}

// Strip web-only assets from the APK (they come from the sherpa_onnx_web package)
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("Assets") }.configureEach {
    doLast {
        val variant = name.replace("merge", "").replace("Assets", "")
        val flutterAssetsDir = layout.buildDirectory.dir("intermediates/flutter/${variant.lowercase()}/flutter_assets").get().asFile
        if (flutterAssetsDir.exists()) {
            delete(fileTree(flutterAssetsDir) {
                include("packages/sherpa_onnx_web/assets/*.wasm")
                include("packages/sherpa_onnx_web/assets/*.js")
            })
        }
    }
}
