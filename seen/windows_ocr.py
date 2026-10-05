"""Use the installed Windows OCR language pack. No service or model download."""
import asyncio
import io


async def recognize(image):
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.graphics.imaging import BitmapDecoder, BitmapPixelFormat, BitmapAlphaMode
    from winrt.windows.storage.streams import InMemoryRandomAccessStream, DataWriter
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError('No Windows OCR language pack available')
    image = image.copy()
    image.thumbnail((OcrEngine.max_image_dimension, OcrEngine.max_image_dimension))
    output = io.BytesIO()
    image.save(output, format='PNG')
    with InMemoryRandomAccessStream() as stream:
        writer = DataWriter(stream)
        writer.write_bytes(output.getvalue())
        await writer.store_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_converted_async(BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED)
        try:
            result = await engine.recognize_async(bitmap)
            return '\n'.join(line.text for line in result.lines)
        finally:
            bitmap.close()


def windows_ocr(image):
    return asyncio.run(asyncio.wait_for(recognize(image), timeout=15))
