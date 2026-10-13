package app.phonestudio.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val Ink = Color(0xFF111922)
val Night = Color(0xFF182431)
val Panel = Color(0xFF22303F)
val PanelRaised = Color(0xFF2D3D4F)
val Slate = Color(0xFFBAC7D9)
val Mist = Color(0xFFF1F4FC)
val Periwinkle = Color(0xFFC1B7F6)
val Peach = Color(0xFFF1C69B)
val Mint = Color(0xFF91DACC)
val Rose = Color(0xFFFFAEB8)

/**
 * One hue per saved backend, in save order.
 *
 * With several Colab sessions running at once, "which machine made this" is the
 * thing the interface has to answer constantly: on the live rail, on every
 * library tile, in the connection list. A colour carries that faster than a name
 * repeated four times, and it is the one place this interface spends colour.
 */
val BackendAccents = listOf(Periwinkle, Peach, Mint)

fun backendAccent(index: Int): Color = BackendAccents[index.coerceAtLeast(0) % BackendAccents.size]

private val StudioColors = darkColorScheme(
    primary = Periwinkle,
    onPrimary = Ink,
    secondary = Mint,
    onSecondary = Ink,
    tertiary = Peach,
    background = Ink,
    onBackground = Mist,
    surface = Night,
    onSurface = Mist,
    surfaceVariant = Panel,
    onSurfaceVariant = Slate,
    error = Rose,
    onError = Ink
)

private val StudioType = Typography(
    displaySmall = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Bold,
        fontSize = 32.sp,
        lineHeight = 38.sp,
        letterSpacing = (-0.6).sp
    ),
    headlineSmall = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 25.sp,
        lineHeight = 31.sp,
        letterSpacing = (-0.3).sp
    ),
    titleMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 16.sp
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontSize = 14.sp,
        lineHeight = 20.sp
    ),
    labelMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 13.sp,
        lineHeight = 18.sp,
        letterSpacing = 0.1.sp
    ),
    labelSmall = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        lineHeight = 17.sp,
        letterSpacing = 0.1.sp
    )
)

@Composable
fun PhoneStudioTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = StudioColors,
        typography = StudioType,
        content = content
    )
}

