plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "app.phonestudio"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.phonestudio"
        minSdk = 26
        targetSdk = 35
        versionCode = 5
        versionName = "0.3.2"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.15"
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    // Reviewed pin: newer Compose 1.12 UI/foundation requires SDK 37 and AGP 9.1.
    //noinspection GradleDependency
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    // Reviewed pin: Core 1.19 requires SDK 37/AGP 9.1; this app builds with SDK 35/AGP 8.7.
    //noinspection GradleDependency
    implementation("androidx.core:core-ktx:1.15.0")
    // Keep the compatible Lifecycle bundle together; 2.11 adds Kotlin 2.x requirements.
    //noinspection GradleDependency
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    // Reviewed pin: Lifecycle Compose 2.11 requires SDK 37/AGP 9.1 and newer Kotlin.
    //noinspection GradleDependency
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    // Reviewed pin: Activity 1.13 requires SDK 36 and AGP 8.9.1.
    //noinspection GradleDependency
    implementation("androidx.activity:activity-compose:1.10.0")
    implementation("androidx.exifinterface:exifinterface:1.4.2")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("io.coil-kt:coil-compose:2.7.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // Serialization 1.7 requires the Kotlin 2.x compiler plugin; this app uses Kotlin 1.9.25.
    //noinspection GradleDependency
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")
    // Local QR decoding only; no scanning app, Play services, or network dependency.
    implementation("com.google.zxing:core:3.5.3")

    testImplementation("junit:junit:4.13.2")

    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
