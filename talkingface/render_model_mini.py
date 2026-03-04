import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import random
import glob
import torch
import numpy as np
import cv2

from talkingface.utils import draw_mouth_maps
from talkingface.models.DINet_mini import input_height,input_width,model_size
from talkingface.model_utils import device
class RenderModel_Mini:
    def __init__(self):
        self.__net = None

    def loadModel(self, ckpt_path):
        # 检查模型文件是否存在
        if not os.path.exists(ckpt_path):
            error_msg = f"模型文件不存在: {ckpt_path}\n\n"
            error_msg += "📦 请下载模型文件：\n"
            error_msg += "   1. 百度网盘: https://pan.baidu.com/s/1jH3WrIAfwI3U5awtnt9KPQ?pwd=ynd7\n"
            error_msg += "   2. Google Drive: https://drive.google.com/drive/folders/1az5WEWOFmh0_yrF3I9DEyctMyjPolo8V?usp=sharing\n\n"
            error_msg += "   下载后，请将模型文件解压到项目根目录的 checkpoint 文件夹中。\n"
            error_msg += f"   期望的文件路径: {os.path.abspath(ckpt_path)}"
            raise FileNotFoundError(error_msg)
        
        from talkingface.models.DINet_mini import DINet_mini_pipeline as DINet
        n_ref = 3
        source_channel = 3
        ref_channel = n_ref * 4
        self.net = DINet(source_channel, ref_channel, device == "cuda").to(device)
        checkpoint = torch.load(ckpt_path, map_location=device)
        net_g_static = checkpoint['state_dict']['net_g']
        self.net.infer_model.load_state_dict(net_g_static)
        self.net.eval()


    def reset_charactor(self, ref_img, ref_keypoints, standard_size = 256):
        ref_img_list = []
        ref_face_edge = draw_mouth_maps(ref_keypoints, size=(standard_size, standard_size))
        # cv2.imshow("ss", ref_face_edge)
        # cv2.waitKey(-1)
        # cv2.imshow("ss", ref_img)
        # cv2.waitKey(-1)
        ref_face_edge = cv2.resize(ref_face_edge, (model_size, model_size))
        ref_img = cv2.resize(ref_img, (model_size, model_size))
        w_pad = int((model_size - input_width) / 2)
        h_pad = int((model_size - input_height) / 2)

        ref_img = np.concatenate(
            [ref_img[h_pad:-h_pad, w_pad:-w_pad, :3], ref_face_edge[h_pad:-h_pad, w_pad:-w_pad, :1]], axis=2)
        # cv2.imshow("ss", ref_face_edge[h_pad:-h_pad, w_pad:-w_pad])
        # cv2.waitKey(-1)
        ref_img_list.append(ref_img)

        teeth_ref_img = os.path.join(current_dir, r"../video_data/teeth_ref/*.png")
        teeth_ref_img = random.sample(glob.glob(teeth_ref_img), 1)[0]
        # teeth_ref_img = teeth_ref_img.replace("_2", "")
        teeth_ref_img = cv2.imread(teeth_ref_img, cv2.IMREAD_UNCHANGED)
        teeth_ref_img = cv2.resize(teeth_ref_img, (input_width, input_height))
        ref_img_list.append(teeth_ref_img)
        ref_img_list.append(teeth_ref_img)

        self.ref_img_save = np.concatenate([i[:,:,:3] for i in ref_img_list], axis=1)
        self.ref_img = np.concatenate(ref_img_list, axis=2)

        ref_tensor = torch.from_numpy(self.ref_img / 255.).float().permute(2, 0, 1).unsqueeze(0).to(device)

        self.net.ref_input(ref_tensor)


    def interface(self, source_tensor, gl_tensor):
        '''

        Args:
            source_tensor: [batch, 3, 128, 128]
            gl_tensor: [batch, 3, 128, 128]

        Returns:
            warped_img: [batch, 3, 128, 128]
        '''
        warped_img = self.net.interface(source_tensor, gl_tensor)
        return warped_img

    def save(self, path):
        torch.save(self.net.state_dict(), path)