import argparse
import os
import json
import shutil
from tqdm import tqdm

import requests
import cv2
import numpy as np

from collections import defaultdict
from pycocotools.coco import COCO
from panopticapi.utils import id2rgb

parser = argparse.ArgumentParser()
parser.add_argument(
    "--coco-json", type=str, required=True, help="Input COCO JSON file"
)
parser.add_argument(
    "--ungroup", type=bool, required=False, default=False, help="If true, sets group id to 0 for group ids which occur only once."
)
parser.add_argument(
    "--skip_bbox_annotations", type=bool, required=False, default=False, help="If true, skips bbox annotations."
)

args = parser.parse_args()

coco_json = args.coco_json
coco_json_folder, coco_json_file = os.path.split(coco_json)

main_dir = os.path.join(os.path.abspath(coco_json) + "__formated")
if not os.path.exists(main_dir):
    os.mkdir(main_dir)

classes_dir = os.path.join(main_dir, "classes")
if not os.path.exists(classes_dir):
    os.mkdir(classes_dir)

json_data = json.load(open(os.path.join(coco_json_folder, coco_json_file)))

classes_loader = []
def_dict = defaultdict(list)


# Downloads images from COCO website
def image_downloader(url):
    file_name_start_pos = url.rfind("/") + 1
    file_name = url[file_name_start_pos:]
    print("downloading: ", url)
    r = requests.get(url, stream=True)
    with open(os.path.join(main_dir, file_name), 'wb') as f:
        f.write(r.content)


# Converts HEX values to RGB values
def hex_to_rgb(hex_string):
    h = hex_string.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# Converts RGB values to HEX values
def rgb_to_hex(rgb_tuple):
    return '#%02x%02x%02x' % rgb_tuple


# Generates blue colors in range(n)
def blue_color_generator(n, hex_values=True):
    hex_colors = []
    for i in range(n):
        int_color = i * 15
        bgr_color = np.array(
            [
                int_color & 255, (int_color >> 8) & 255,
                (int_color >> 16) & 255, 255
            ],
            dtype=np.uint8
        )
        hex_color = '#' + "{:02x}".format(
            bgr_color[2]
        ) + "{:02x}".format(bgr_color[1], ) + "{:02x}".format(bgr_color[0])
        if hex_values:
            hex_colors.append(hex_color)
        else:
            hex_colors.append(hex_to_rgb(hex_color))
    return hex_colors


# Converts RLE format to polygon segmentation for object detection and keypoints
def rle_to_polygon(annotation):
    coco = COCO(coco_json)
    binary_mask = coco.annToMask(annotation)
    contours, hierarchy = cv2.findContours(
        binary_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    segmentation = []

    for contour in contours:
        contour = contour.flatten().tolist()
        if len(contour) > 4:
            segmentation.append(contour)
        if len(segmentation) == 0:
            continue
    return segmentation


# Returns unique values of list. Values can be dicts or lists!
def dict_setter(list_of_dicts):
    print(list_of_dicts[1:5])
    return [
        d for n, d in enumerate(list_of_dicts) if d not in list_of_dicts[n + 1:]
    ]


# For copying png files
def copy_png():
    # you can change path if the folder and JSON file aren't in the same directory
    path = os.path.join(coco_json_folder, 'panoptic_masks')
    for root, dirs, files in os.walk(path, topdown=False):
        for file in files:
            for ann in json_data['annotations']:
                if os.path.isfile(os.path.join(root, file)):
                    shutil.copy(
                        os.path.join(root, ann['file_name']),
                        os.path.join(main_dir, ann['file_name'])
                    )


# For renaming png files
def rename_png():
    for root, dirs, files in os.walk(main_dir, topdown=False):
        for file in files:
            for image in json_data['images']:
                if file.endswith('.png'
                                ) and str(file)[:-3] == image['file_name'][:-3]:
                    new_name = image['file_name'] + '___save.png'
                    os.rename(
                        os.path.join(root, file), os.path.join(root, new_name)
                    )

def write_annotations_to_files(image_id_to_annotations, json_data):
    for img in tqdm(json_data['images'], "Writing annotations to disk"):
        if img['id'] not in image_id_to_annotations:
            continue
        f_loader = image_id_to_annotations[img['id']]
        if 'file_name' in img:
            image_path = img['file_name']
        else:
            image_path = img['coco_url'].split('/')[-1]
        with open(
            os.path.join(
                main_dir, image_path + "___objects.json"
            ), "w"
        ) as new_json:
            json.dump(f_loader, new_json, indent=2)

def generate_sa_annotations(json_data):
    cat_id_to_cat = {}
    for cat in json_data['categories']:
        cat_id_to_cat[cat['id']] = cat
    for annot in json_data['annotations']:
        if 'iscrowd' in annot and annot['iscrowd'] == 1:
            try:
                annot['segmentation'] = rle_to_polygon(annot)
            except IndexError:
                print("List index out of range")
        cat = cat_id_to_cat[annot['category_id']]
        sa_dict_bbox = {
            'type': 'bbox',
            'points':
                {
                    'x1': annot['bbox'][0],
                    'y1': annot['bbox'][1],
                    'x2': annot['bbox'][0] + annot['bbox'][2],
                    'y2': annot['bbox'][1] + annot['bbox'][3]
                },
            'className': cat['name'],
            'classId': cat['id'],
            'attributes': [],
            'probability': 100,
            'locked': False,
            'visible': True,
            'groupId': annot['id'],
            'imageId': annot['image_id']
        }

        sa_polygon_loader = [
            {
                'type': 'polygon',
                'points': polygon,
                'className': cat['name'],
                'classId': cat['id'],
                'attributes': [],
                'probability': 100,
                'locked': False,
                'visible': True,
                'groupId': annot['id'],
                'imageId': annot['image_id']
            } for polygon in annot['segmentation']
        ]
        yield (sa_dict_bbox, sa_polygon_loader)

# We certainly don't need to download all the coco images for instance annotations. 
# Not sure about the others so far.
if 'instances' not in str(coco_json_file):
    # For the case if you need dataset's original images
    for image in json_data['images']:
        image_downloader(image['coco_url'])

# Classes
print("Number of categories is {}".format(len(json_data['categories'])))
for c, data in enumerate(json_data['categories']):
    colors = blue_color_generator(len(json_data['categories']))
    classes_dict = {
        'name': data['name'],
        'id': data['id'],
        'color': colors[c],
        'attribute_groups': []
    }
    classes_loader.append(classes_dict)
res_list = classes_loader


with open(os.path.join(classes_dir, "classes.json"), "w") as classes_json:
    json.dump(res_list, classes_json, indent=2)

# instances
if 'instances' in str(coco_json_file):
    image_id_to_annotations = {}
    group_id_occurence_counts = {}
    for (sa_dict_bbox, sa_polygon_loader) in tqdm(generate_sa_annotations(json_data), "Counting group occurence frequencies."):
        for polygon in sa_polygon_loader:
            if polygon['groupId'] in group_id_occurence_counts.keys():
                group_id_occurence_counts[polygon['groupId']] += 1
            else:
                group_id_occurence_counts[polygon['groupId']] = 1
    for (sa_dict_bbox, sa_polygon_loader) in tqdm(generate_sa_annotations(json_data), "Converting annotations."):
        for polygon in sa_polygon_loader:
            if args.ungroup and (group_id_occurence_counts[polygon['groupId']] == 1):
                polygon['groupId'] = 0
            if polygon['imageId'] not in image_id_to_annotations:
                image_id_to_annotations[polygon['imageId']] = [polygon]
            else:
                image_id_to_annotations[polygon['imageId']].append(polygon)
            if not args.skip_bbox_annotations:
                if sa_dict_bbox['imageId'] not in image_id_to_annotations:
                    image_id_to_annotations[sa_dict_bbox['imageId']] = [sa_dict_bbox]
                else:
                    image_id_to_annotations[sa_dict_bbox['imageId']].append(sa_dict_bbox)

    write_annotations_to_files(image_id_to_annotations, json_data)
# panoptic
elif 'panoptic' in str(coco_json_file):
    print("Converting panoptic annotations.") 
    copy_png()
    rename_png()

    pan_loader = []
    for annot in json_data['annotations']:
        for cat in json_data['categories']:
            blue_colors = blue_color_generator(len(annot['segments_info']))
            for i, si in enumerate(annot['segments_info']):

                if cat['id'] == si['category_id']:
                    sa_dict = {
                        'classId': cat['id'],
                        'probability': 100,
                        'visible': True,
                        'parts':
                            [{
                                # 'color': rgb_to_hex(tuple(id2rgb(si['id'])))
                                'color': blue_colors[i]
                            }],
                        'attributes': [],
                        'attributeNames': [],
                        'imageId': annot['image_id']
                    }

                    pan_loader.append((sa_dict['imageId'], sa_dict))

    for img in json_data['images']:
        f_loader = []
        for img_id, img_data in pan_loader:
            if img['id'] == img_id:
                f_loader.append(img_data)
                with open(
                    os.path.join(main_dir, img['file_name'] + "___pixel.json"),
                    "w"
                ) as new_json:
                    json.dump(dict_setter(f_loader), new_json, indent=2)

# keypoints
elif 'keypoints' in str(coco_json_file):
    print("Converting keypoint annotations.") 
    kp_loader = []

    for annot in json_data['annotations']:
        if annot['num_keypoints'] > 0:
            sa_points = [
                item for index, item in enumerate(annot['keypoints'])
                if (index + 1) % 3 != 0
            ]

            for n, i in enumerate(sa_points):
                if i == 0:
                    sa_points[n] = -17
            sa_points = [
                (sa_points[i], sa_points[i + 1])
                for i in range(0, len(sa_points), 2)
            ]
            print(sa_points)
            for cat in json_data['categories']:
                keypoint_names = cat['keypoints']

                if annot['iscrowd'] == 1:
                    annot['segmentation'] = rle_to_polygon(annot)

                if cat['id'] == annot['category_id']:

                    sa_dict_bbox = {
                        'type': 'bbox',
                        'points':
                            {
                                'x1': annot['bbox'][0],
                                'y1': annot['bbox'][1],
                                'x2': annot['bbox'][0] + annot['bbox'][2],
                                'y2': annot['bbox'][1] + annot['bbox'][3]
                            },
                        'className': cat['name'],
                        'classId': cat['id'],
                        'pointLabels': {},
                        'attributes': [],
                        'probability': 100,
                        'locked': False,
                        'visible': True,
                        'groupId': annot['id'],
                        'imageId': annot['image_id']
                    }

                    sa_polygon_loader = [
                        {
                            'type': 'polygon',
                            'points': polygon,
                            'className': cat['name'],
                            'classId': cat['id'],
                            'pointLabels': {},
                            'attributes': [],
                            'probability': 100,
                            'locked': False,
                            'visible': True,
                            'groupId': annot['id'],
                            'imageId': annot['image_id']
                        } for polygon in annot['segmentation']
                    ]

                    sa_template = {
                        'type': 'template',
                        'classId': cat['id'],
                        'probability': 100,
                        'points': [],
                        'connections': [],
                        'attributes': [],
                        'attributeNames': [],
                        'groupId': annot['id'],
                        'pointLabels': {},
                        'locked': False,
                        'visible': True,
                        'templateId': -1,
                        'className': cat['name'],
                        'templateName': 'skeleton',
                        'imageId': annot['image_id']
                    }
                    for kp_name in keypoint_names:
                        pl_key = keypoint_names.index(kp_name)
                        sa_template['pointLabels'][pl_key] = kp_name

                    for connection in cat['skeleton']:
                        index = cat['skeleton'].index(connection)
                        sa_template['connections'].append(
                            {
                                'id': index + 1,
                                'from': cat['skeleton'][index][0],
                                'to': cat['skeleton'][index][1]
                            }
                        )

                    for point in sa_points:
                        point_index = sa_points.index(point)
                        sa_template['points'].append(
                            {
                                'id': point_index + 1,
                                'x': sa_points[point_index][0],
                                'y': sa_points[point_index][1]
                            }
                        )

                    for img in json_data['images']:
                        for polygon in sa_polygon_loader:
                            if polygon['imageId'] == img['id']:
                                kp_loader.append((img['id'], polygon))
                            if sa_dict_bbox['imageId'] == img['id']:
                                kp_loader.append((img['id'], sa_dict_bbox))
                            if sa_template['imageId'] == img['id']:
                                kp_loader.append((img['id'], sa_template))

        for img in json_data['images']:
            f_loader = []
            for img_id, img_data in kp_loader:
                if img['id'] == img_id:
                    f_loader.append(img_data)
            with open(
                os.path.join(main_dir, img['file_name'] + "___objects.json"),
                "w"
            ) as new_json:
                json.dump(dict_setter(f_loader), new_json, indent=2)
