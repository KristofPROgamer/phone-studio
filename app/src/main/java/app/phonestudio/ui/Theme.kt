package app.phonestudio.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val Ink = Color(0xFF111827)
val Night = Color(0xFF191F33)
val Panel = Color(0xFF222A42)
val PanelRaised = Color(0xFF2A3452)
val Slate = Color(0xFF909BB9)
val Mist = Color(0xFFF2F4FF)
val Periwinkle = Color(0xFFAEBBFF)
val Peach = Color(0xFFF4C28C)
val Mint = Color(0xFF8DE0C6)
val Rose = Color(0xFFFFB2B9)

private val StudioColors = darkColorScheme(
    primary = Periwinkle,
    onPrimary = Ink,
    secondary = Peach,
    onSecondary = Ink,
    tertiary = Mint,
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
        fontFamily = FontFamily.Serif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 34.sp,
        letterSpacing = (-0.7).sp
    ),
    headlineSmall = TextStyle(
        fontFamily = FontFamily.Serif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 25.sp
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
        fontFamily = FontFamily.Monospace,
        fontWeight = FontWeight.Bold,
        fontSize = 11.sp,
        letterSpacing = 0.8.sp
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

