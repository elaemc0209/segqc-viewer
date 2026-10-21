"""Generate artificial CT + mask data. Contains no patient data."""
import argparse
import gzip
import struct
from pathlib import Path

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid


def create_demo(destination):
    destination = Path(destination)
    images = destination / "影像" / "synthetic_case"
    masks = destination / "masks"
    images.mkdir(parents=True, exist_ok=True)
    masks.mkdir(parents=True, exist_ok=True)
    z, y, x = np.mgrid[:24, :64, :64]
    body = ((x - 32) / 28) ** 2 + ((y - 32) / 24) ** 2 < 1
    target = ((x - 32) / 12) ** 2 + ((y - 34) / 10) ** 2 + ((z - 12) / 9) ** 2 < 1
    pixels = np.where(body, 40, -1000).astype(np.int16)
    pixels[target] = 15
    study, series, frame = generate_uid(), generate_uid(), generate_uid()
    for k in range(len(pixels)):
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        ds = FileDataset(str(images / f"{k:03}.dcm"), {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID = CTImageStorage
        ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID = study, series
        ds.FrameOfReferenceUID = frame
        ds.Modality, ds.PatientName, ds.PatientID = "CT", "SYNTHETIC^DEMO", "synthetic_case"
        ds.Rows, ds.Columns = pixels.shape[1:]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [0, 0, k * 2]
        ds.PixelSpacing, ds.SliceThickness = [1, 1], 2
        ds.InstanceNumber = k + 1
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 1
        ds.RescaleSlope, ds.RescaleIntercept = 1, 0
        ds.PixelData = pixels[k].tobytes()
        ds.save_as(ds.filename, enforce_file_format=True)
    header = bytearray(352)
    struct.pack_into("<i", header, 0, 348)
    struct.pack_into("<8h", header, 40, 3, 64, 64, 24, 1, 1, 1, 1)
    struct.pack_into("<hh", header, 70, 2, 8)
    struct.pack_into("<8f", header, 76, 1, 1, 1, 2, 1, 1, 1, 1)
    struct.pack_into("<f", header, 108, 352)
    header[123] = 2  # millimetres
    struct.pack_into("<h", header, 254, 1)
    struct.pack_into("<12f", header, 280, -1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 2, 0)
    header[344:348] = b"n+1\0"
    with gzip.open(masks / "synthetic_case.nii.gz", "wb") as stream:
        stream.write(header)
        stream.write(target.astype(np.uint8).tobytes())
    return pixels, target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    create_demo(parser.parse_args().destination)
