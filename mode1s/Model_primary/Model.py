import multiprocessing
import operator
from functools import partial

import numpy as np

from core import mathlib
from core.interact import interact as io
from core.leras import nn
from facelib import FaceType
from mode1s import ModelBase
from samplelib import *

class HackFakeModel(ModelBase):

    #override
    def on_initialize_options(self):
        device_config = nn.getCurrentDeviceConfig()

        lowest_vram = 2
        if len(device_config.devices) != 0:
            lowest_vram = device_config.devices.get_worst_device().total_mem_gb

        if lowest_vram >= 4:
            suggest_batch_size = 8
        else:
            suggest_batch_size = 4

        yn_str = {True:'y',False:'n'}
        min_res = 64
        max_res = 640

        default_resolution         = self.options['resolution']         = self.load_or_def_option('resolution', 128)
        default_face_type          = self.options['face_type']          = self.load_or_def_option('face_type', 'f')
        default_models_opt_on_gpu  = self.options['models_opt_on_gpu']  = self.load_or_def_option('models_opt_on_gpu', True)

        archi = self.load_or_def_option('archi', 'liae-ud')
        archi = {'dfuhd':'df-u','liaeuhd':'liae-u'}.get(archi, archi) #backward comp
        default_archi              = self.options['archi'] = archi

        default_ae_dims            = self.options['ae_dims']            = self.load_or_def_option('ae_dims', 256)
        default_e_dims             = self.options['e_dims']             = self.load_or_def_option('e_dims', 64)
        default_d_dims             = self.options['d_dims']             = self.options.get('d_dims', None)
        default_d_mask_dims        = self.options['d_mask_dims']        = self.options.get('d_mask_dims', None)
        default_masked_training    = self.options['masked_training']    = self.load_or_def_option('masked_training', True)
        default_eyes_mouth_prio    = self.options['eyes_mouth_prio']    = self.load_or_def_option('eyes_mouth_prio', False)
        default_uniform_yaw        = self.options['uniform_yaw']        = self.load_or_def_option('uniform_yaw', False)

        default_adabelief          = self.options['adabelief']          = self.load_or_def_option('adabelief', True)

        lr_dropout = self.load_or_def_option('lr_dropout', 'n')
        lr_dropout = {True:'y', False:'n'}.get(lr_dropout, lr_dropout) #backward comp
        default_lr_dropout         = self.options['lr_dropout'] = lr_dropout

        default_random_warp        = self.options['random_warp']        = self.load_or_def_option('random_warp', True)
        default_true_face_power    = self.options['true_face_power']    = self.load_or_def_option('true_face_power', 0.0)
        default_face_style_power   = self.options['face_style_power']   = self.load_or_def_option('face_style_power', 0.0)
        default_bg_style_power     = self.options['bg_style_power']     = self.load_or_def_option('bg_style_power', 0.0)
        default_ct_mode            = self.options['ct_mode']            = self.load_or_def_option('ct_mode', 'none')
        default_clipgrad           = self.options['clipgrad']           = self.load_or_def_option('clipgrad', False)
        default_pretrain           = self.options['pretrain']           = self.load_or_def_option('pretrain', False)

        ask_override = self.ask_override()
        if self.is_first_run() or ask_override:
            self.ask_autobackup_hour()
            self.ask_write_preview_history()
            self.ask_target_iter()
            self.ask_random_flip()
            self.ask_batch_size(suggest_batch_size)

        if self.is_first_run():
            resolution = io.input_int("设置模型分辨率，简称RS，根据自己显存大小以及用途选择<默认为16的倍数>", default_resolution, add_info="64-640", help_message="More resolution requires more VRAM and time to train. Value will be adjusted to multiple of 16 and 32 for -d archi.")
            resolution = np.clip ( (resolution // 16) * 16, min_res, max_res)
            self.options['resolution'] = resolution



            self.options['face_type'] = io.input_str ("选择人脸训练范围,半脸<h>/中脸<mf>/全脸<f>/整张脸<wf>/头部<head>", default_face_type, ['h','mf','f','wf','head'], help_message="Half / mid face / full face / whole face / head. Half face has better resolution, but covers less area of cheeks. Mid face is 30% wider than half face. 'Whole face' covers full area of face include forehead. 'head' covers full head, but requires XSeg for src and dst faceset.").lower()

            while True:
                archi = io.input_str ("选择模型架构，简称archi，HD后缀为高清架构，UHD后缀为超高清架构", default_archi, help_message=\
"""
'df' keeps more identity-preserved face.
'liae' can fix overly different face shapes.
'-u' increased likeness of the face.
'-d' (experimental) doubling the resolution using the same computation cost.
Examples: df, liae, df-d, df-ud, liae-ud, ...
""").lower()

                archi_split = archi.split('-')

                if len(archi_split) == 2:
                    archi_type, archi_opts = archi_split
                elif len(archi_split) == 1:
                    archi_type, archi_opts = archi_split[0], None
                else:
                    continue

                if archi_type not in ['df', 'liae']:
                    continue

                if archi_opts is not None:
                    if len(archi_opts) == 0:
                        continue
                    if len([ 1 for opt in archi_opts if opt not in ['u','d'] ]) != 0:
                        continue

                    if 'd' in archi_opts:
                        self.options['resolution'] = np.clip ( (self.options['resolution'] // 32) * 32, min_res, max_res)

                break
            self.options['archi'] = archi

        default_d_dims             = self.options['d_dims']             = self.load_or_def_option('d_dims', 64)

        default_d_mask_dims        = default_d_dims // 3
        default_d_mask_dims        += default_d_mask_dims % 2
        default_d_mask_dims        = self.options['d_mask_dims']        = self.load_or_def_option('d_mask_dims', default_d_mask_dims)

        if self.is_first_run():
            self.options['ae_dims'] = np.clip ( io.input_int("设置自动编码器数量，简称ae_dims", default_ae_dims, add_info="32-1024", help_message="All face information will packed to AE dims. If amount of AE dims are not enough, then for example closed eyes will not be recognized. More dims are better, but require more VRAM. You can fine-tune model size to fit your GPU." ), 32, 1024 )

            e_dims = np.clip ( io.input_int("设置编码器数量，简称e_dims", default_e_dims, add_info="16-256", help_message="More dims help to recognize more facial features and achieve sharper result, but require more VRAM. You can fine-tune model size to fit your GPU." ), 16, 256 )
            self.options['e_dims'] = e_dims + e_dims % 2

            d_dims = np.clip ( io.input_int("设置解码器数量，简称d_dims", default_d_dims, add_info="16-256", help_message="More dims help to recognize more facial features and achieve sharper result, but require more VRAM. You can fine-tune model size to fit your GPU." ), 16, 256 )
            self.options['d_dims'] = d_dims + d_dims % 2

            d_mask_dims = np.clip ( io.input_int("设置遮罩解码器数量，简称d_mask_dims<默认为编码器的1/3>", default_d_mask_dims, add_info="16-256", help_message="Typical mask dimensions = decoder dimensions / 3. If you manually cut out obstacles from the dst mask, you can increase this parameter to achieve better quality." ), 16, 256 )
            self.options['d_mask_dims'] = d_mask_dims + d_mask_dims % 2

        if self.is_first_run() or ask_override:
            if self.options['face_type'] == 'wf' or self.options['face_type'] == 'head':
                self.options['masked_training']  = io.input_bool ("是否启用面具训练?<当脸部训练清晰后，关闭训练周围，增加融合度！>", default_masked_training, help_message="This option is available only for 'whole_face' or 'head' type. Masked training clips training area to full_face mask or XSeg mask, thus network will train the faces properly.")

            self.options['eyes_mouth_prio'] = io.input_bool ("是否启用眼睛和嘴巴优先训练?<修复训练中的眼睛问题，使牙齿细节更高!>", default_eyes_mouth_prio, help_message='Helps to fix eye problems during training like "alien eyes" and wrong eyes direction. Also makes the detail of the teeth higher.')
            self.options['uniform_yaw'] = io.input_bool ("是否启用统一样本侧脸角度排序训练？<有助于修复一些比较模糊的侧脸，仅在大部份素材都训练清晰后，少量侧脸不清晰时有效！>", default_uniform_yaw, help_message='Helps to fix blurry side faces due to small amount of them in the faceset.')

        default_gan_power          = self.options['gan_power']          = self.load_or_def_option('gan_power', 0.0)
        default_gan_patch_size     = self.options['gan_patch_size']     = self.load_or_def_option('gan_patch_size', self.options['resolution'] // 8)
        default_gan_dims           = self.options['gan_dims']           = self.load_or_def_option('gan_dims', 16)

        if self.is_first_run() or ask_override:
            self.options['models_opt_on_gpu'] = io.input_bool ("是否将模型及优化器放置在GPU上?", default_models_opt_on_gpu, help_message="When you train on one GPU, by default model and optimizer weights are placed on GPU to accelerate the process. You can place they on CPU to free up extra VRAM, thus set bigger dimensions.")

            self.options['adabelief'] = io.input_bool ("是否启用AdaBelief优化程序？<可以加快模型收敛速度，但是需要更多的VRAM！>", default_adabelief, help_message="Use AdaBelief optimizer. It requires more VRAM, but the accuracy and the generalization of the model is higher.")

            self.options['lr_dropout']  = io.input_str (f"是否启用学习率?<开启后会增加清晰度！>", default_lr_dropout, ['n','y','cpu'], help_message="When the face is trained enough, you can enable this option to get extra sharpness and reduce subpixel shake for less amount of iterations. Enabled it before `disable random warp` and before GAN. \nn - disabled.\ny - enabled\ncpu - enabled on CPU. This allows not to use extra VRAM, sacrificing 20% time of iteration.")

				
            self.options['random_warp'] = io.input_bool ("是否启用人脸随机扭曲?<如果SRC脸部表情没有DST丰富，请开启！>", default_random_warp, help_message="Random warp is required to generalize facial expressions of both faces. When the face is trained enough, you can disable it to get extra sharpness and reduce subpixel shake for less amount of iterations.")

            self.options['gan_power'] = np.clip ( io.input_number ("是否启用对抗性网络?<仅在关闭随机扭曲及学习率训练后才能开启，并且不能关闭!推荐值0.1>", default_gan_power, add_info="0.0 .. 1.0", help_message="Forces the neural network to learn small details of the face. Enable it only when the face is trained enough with lr_dropout(on) and random_warp(off), and don't disable. The higher the value, the higher the chances of artifacts. Typical fine value is 0.1"), 0.0, 1.0 )

            if self.options['gan_power'] != 0.0:                
                gan_patch_size = np.clip ( io.input_int("设置对抗网络补丁数值!<数值越大效果越好，但需要的显存越多，推荐值为模型分辨率的1/8>", default_gan_patch_size, add_info="3-640", help_message="The higher patch size, the higher the quality, the more VRAM is required. You can get sharper edges even at the lowest setting. Typical fine value is resolution / 8." ), 3, 640 )
                self.options['gan_patch_size'] = gan_patch_size

                gan_dims = np.clip ( io.input_int("设置对抗网络维度数值!<数值越大效果越好，但需要的显存越多，推荐值为16>", default_gan_dims, add_info="4-64", help_message="The dimensions of the GAN network. The higher dimensions, the more VRAM is required. You can get sharper edges even at the lowest setting. Typical fine value is 16." ), 4, 64 )
                self.options['gan_dims'] = gan_dims
            else:
                self.options['gan_patch_size'] = 0.0
                self.options['gan_dims'] = 0.0

            if 'df' in self.options['archi']:
                self.options['true_face_power'] = np.clip ( io.input_number ("设置“True face”强度，<数值越大，训练效果越像SRC，推荐数值0.01>", default_true_face_power, add_info="0.0000 .. 1.0", help_message="Experimental option. Discriminates result face to be more like src face. Higher value - stronger discrimination. Typical value is 0.01 . Comparison - https://i.imgur.com/czScS9q.png"), 0.0, 1.0 )
            else:
                self.options['true_face_power'] = 0.0

            self.options['face_style_power'] = np.clip ( io.input_number("设置面部风格训练强度，<学习DST面部细节，但是有风险，推荐值：0.001>", default_face_style_power, add_info="0.0..100.0", help_message="Learn the color of the predicted face to be the same as dst inside mask. If you want to use this option with 'whole_face' you have to use XSeg trained mask. Warning: Enable it only after 10k iters, when predicted face is clear enough to start learn style. Start from 0.001 value and check history changes. Enabling this option increases the chance of model collapse."), 0.0, 100.0 )
            self.options['bg_style_power'] = np.clip ( io.input_number("设置背景训练强度，<将DST的背景转移到训练效果！>", default_bg_style_power, add_info="0.0..100.0", help_message="Learn the area outside mask of the predicted face to be the same as dst. If you want to use this option with 'whole_face' you have to use XSeg trained mask. For whole_face you have to use XSeg trained mask. This can make face more like dst. Enabling this option increases the chance of model collapse. Typical value is 2.0"), 0.0, 100.0 )

            self.options['ct_mode'] = io.input_str (f"设置色彩转换模式训练，以匹配肤色，", default_ct_mode, ['none','rct','lct','mkl','idt','sot'], help_message="Change color distribution of src samples close to dst samples. Try all modes to find the best.")
            self.options['clipgrad'] = io.input_bool ("是否启用梯形裁剪，防止模型崩溃，", default_clipgrad, help_message="Gradient clipping reduces chance of model collapse, sacrificing speed of training.")

            self.options['pretrain'] = io.input_bool ("是否启用预训练，<预训练一般不推荐使用，默认带的是欧美人脸数据集！>", default_pretrain, help_message="Pretrain the model with large amount of various faces. After that, model can be used to train the fakes more quickly.")
        if self.options['pretrain'] and self.get_pretraining_data_path() is None:
            raise Exception("训练所需的素材不存在！")

        self.gan_model_changed = (default_gan_patch_size != self.options['gan_patch_size']) or (default_gan_dims != self.options['gan_dims'])

        self.pretrain_just_disabled = (default_pretrain == True and self.options['pretrain'] == False)

    #override
    def on_initialize(self):
        device_config = nn.getCurrentDeviceConfig()
        devices = device_config.devices
        self.model_data_format = "NCHW" if len(devices) != 0 and not self.is_debug() else "NHWC"
        nn.initialize(data_format=self.model_data_format)
        tf = nn.tf

        self.resolution = resolution = self.options['resolution']
        self.face_type = {'h'  : FaceType.HALF,
                          'mf' : FaceType.MID_FULL,
                          'f'  : FaceType.FULL,
                          'wf' : FaceType.WHOLE_FACE,
                          'head' : FaceType.HEAD}[ self.options['face_type'] ]

        if 'eyes_prio' in self.options:
            self.options.pop('eyes_prio')

        eyes_mouth_prio = self.options['eyes_mouth_prio']

        archi_split = self.options['archi'].split('-')

        if len(archi_split) == 2:
            archi_type, archi_opts = archi_split
        elif len(archi_split) == 1:
            archi_type, archi_opts = archi_split[0], None

        ae_dims = self.options['ae_dims']
        e_dims = self.options['e_dims']
        d_dims = self.options['d_dims']
        d_mask_dims = self.options['d_mask_dims']
        self.pretrain = self.options['pretrain']
        if self.pretrain_just_disabled:
            self.set_iter(0)

        adabelief = self.options['adabelief']

        self.gan_power = gan_power = 0.0 if self.pretrain else self.options['gan_power']
        random_warp = False if self.pretrain else self.options['random_warp']

        if self.pretrain:
            self.options_show_override['gan_power'] = 0.0
            self.options_show_override['random_warp'] = False
            self.options_show_override['lr_dropout'] = 'n'
            self.options_show_override['face_style_power'] = 0.0
            self.options_show_override['bg_style_power'] = 0.0
            self.options_show_override['uniform_yaw'] = True

        masked_training = self.options['masked_training']
        ct_mode = self.options['ct_mode']
        if ct_mode == 'none':
            ct_mode = None

        models_opt_on_gpu = False if len(devices) == 0 else self.options['models_opt_on_gpu']
        models_opt_device = '/GPU:0' if models_opt_on_gpu and self.is_training else '/CPU:0'
        optimizer_vars_on_cpu = models_opt_device=='/CPU:0'

        input_ch=3
        bgr_shape = nn.get4Dshape(resolution,resolution,input_ch)
        mask_shape = nn.get4Dshape(resolution,resolution,1)
        self.model_filename_list = []

        with tf.device ('/CPU:0'):
            #Place holders on CPU
            self.warped_src = tf.placeholder (nn.floatx, bgr_shape)
            self.warped_dst = tf.placeholder (nn.floatx, bgr_shape)

            self.target_src = tf.placeholder (nn.floatx, bgr_shape)
            self.target_dst = tf.placeholder (nn.floatx, bgr_shape)

            self.target_srcm    = tf.placeholder (nn.floatx, mask_shape)
            self.target_srcm_em = tf.placeholder (nn.floatx, mask_shape)
            self.target_dstm    = tf.placeholder (nn.floatx, mask_shape)
            self.target_dstm_em = tf.placeholder (nn.floatx, mask_shape)

        # Initializing model classes
        model_archi = nn.DeepFakeArchi(resolution, opts=archi_opts)

        with tf.device (models_opt_device):
            if 'df' in archi_type:
                self.encoder = model_archi.Encoder(in_ch=input_ch, e_ch=e_dims, name='encoder')
                encoder_out_ch = self.encoder.get_out_ch()*self.encoder.get_out_res(resolution)**2

                self.inter = model_archi.Inter (in_ch=encoder_out_ch, ae_ch=ae_dims, ae_out_ch=ae_dims, name='inter')
                inter_out_ch = self.inter.get_out_ch()

                self.decoder_src = model_archi.Decoder(in_ch=inter_out_ch, d_ch=d_dims, d_mask_ch=d_mask_dims, name='decoder_src')
                self.decoder_dst = model_archi.Decoder(in_ch=inter_out_ch, d_ch=d_dims, d_mask_ch=d_mask_dims, name='decoder_dst')

                self.model_filename_list += [ [self.encoder,     '20201001.tar'],
                                              [self.inter,       '20201002.tar'],
                                              [self.decoder_src, '20201003.tar'],
                                              [self.decoder_dst, '20201004.tar']  ]

                if self.is_training:
                    if self.options['true_face_power'] != 0:
                        self.code_discriminator = nn.CodeDiscriminator(ae_dims, code_res=self.inter.get_out_res(), name='dis' )
                        self.model_filename_list += [ [self.code_discriminator, '20201005.tar'] ]

            elif 'liae' in archi_type:
                self.encoder = model_archi.Encoder(in_ch=input_ch, e_ch=e_dims, name='encoder')
                encoder_out_ch = self.encoder.get_out_ch()*self.encoder.get_out_res(resolution)**2

                self.inter_AB = model_archi.Inter(in_ch=encoder_out_ch, ae_ch=ae_dims, ae_out_ch=ae_dims*2, name='inter_AB')
                self.inter_B  = model_archi.Inter(in_ch=encoder_out_ch, ae_ch=ae_dims, ae_out_ch=ae_dims*2, name='inter_B')

                inter_out_ch = self.inter_AB.get_out_ch() 
                inters_out_ch = inter_out_ch*2
                self.decoder = model_archi.Decoder(in_ch=inters_out_ch, d_ch=d_dims, d_mask_ch=d_mask_dims, name='decoder')

                self.model_filename_list += [ [self.encoder,  '20201001.tar'],
                                              [self.inter_AB, '20201007.tar'],
                                              [self.inter_B , '20201008.tar'],
                                              [self.decoder , '20201009.tar'] ]

            if self.is_training:
                if gan_power != 0:
                    self.D_src = nn.UNetPatchDiscriminator(patch_size=self.options['gan_patch_size'], in_ch=input_ch, base_ch=self.options['gan_dims'], name="D_src")
                    self.model_filename_list += [ [self.D_src, '20201006.tar'] ]

                # Initialize optimizers
                lr=5e-5
                lr_dropout = 0.3 if self.options['lr_dropout'] in ['y','cpu'] and not self.pretrain else 1.0
                OptimizerClass = nn.AdaBelief if adabelief else nn.RMSprop
                clipnorm = 1.0 if self.options['clipgrad'] else 0.0

                if 'df' in archi_type:
                    self.src_dst_trainable_weights = self.encoder.get_weights() + self.inter.get_weights() + self.decoder_src.get_weights() + self.decoder_dst.get_weights()
                elif 'liae' in archi_type:
                    self.src_dst_trainable_weights = self.encoder.get_weights() + self.inter_AB.get_weights() + self.inter_B.get_weights() + self.decoder.get_weights()



                self.src_dst_opt = OptimizerClass(lr=lr, lr_dropout=lr_dropout, clipnorm=clipnorm, name='src_dst_opt')
                self.src_dst_opt.initialize_variables (self.src_dst_trainable_weights, vars_on_cpu=optimizer_vars_on_cpu, lr_dropout_on_cpu=self.options['lr_dropout']=='cpu')
                self.model_filename_list += [ (self.src_dst_opt, '20201010.tar') ]

                if self.options['true_face_power'] != 0:
                    self.D_code_opt = OptimizerClass(lr=lr, lr_dropout=lr_dropout, clipnorm=clipnorm, name='D_code_opt')
                    self.D_code_opt.initialize_variables ( self.code_discriminator.get_weights(), vars_on_cpu=optimizer_vars_on_cpu, lr_dropout_on_cpu=self.options['lr_dropout']=='cpu')
                    self.model_filename_list += [ (self.D_code_opt, '20201011.tar') ]

                if gan_power != 0:
                    self.D_src_dst_opt = OptimizerClass(lr=lr, lr_dropout=lr_dropout, clipnorm=clipnorm, name='GAN_opt')
                    self.D_src_dst_opt.initialize_variables ( self.D_src.get_weights(), vars_on_cpu=optimizer_vars_on_cpu, lr_dropout_on_cpu=self.options['lr_dropout']=='cpu')#+self.D_src_x2.get_weights()
                    self.model_filename_list += [ (self.D_src_dst_opt, '20201012.tar') ]

        if self.is_training:
            # Adjust batch size for multiple GPU
            gpu_count = max(1, len(devices) )
            bs_per_gpu = max(1, self.get_batch_size() // gpu_count)
            self.set_batch_size( gpu_count*bs_per_gpu)


            # Compute losses per GPU
            gpu_pred_src_src_list = []
            gpu_pred_dst_dst_list = []
            gpu_pred_src_dst_list = []
            gpu_pred_src_srcm_list = []
            gpu_pred_dst_dstm_list = []
            gpu_pred_src_dstm_list = []

            gpu_src_losses = []
            gpu_dst_losses = []
            gpu_G_loss_gvs = []
            gpu_D_code_loss_gvs = []
            gpu_D_src_dst_loss_gvs = []
            for gpu_id in range(gpu_count):
                with tf.device( f'/GPU:{gpu_id}' if len(devices) != 0 else f'/CPU:0' ):

                    with tf.device(f'/CPU:0'):
                        # slice on CPU, otherwise all batch data will be transfered to GPU first
                        batch_slice = slice( gpu_id*bs_per_gpu, (gpu_id+1)*bs_per_gpu )
                        gpu_warped_src      = self.warped_src [batch_slice,:,:,:]
                        gpu_warped_dst      = self.warped_dst [batch_slice,:,:,:]
                        gpu_target_src      = self.target_src [batch_slice,:,:,:]
                        gpu_target_dst      = self.target_dst [batch_slice,:,:,:]
                        gpu_target_srcm       = self.target_srcm[batch_slice,:,:,:]
                        gpu_target_srcm_em = self.target_srcm_em[batch_slice,:,:,:]
                        gpu_target_dstm       = self.target_dstm[batch_slice,:,:,:]
                        gpu_target_dstm_em = self.target_dstm_em[batch_slice,:,:,:]

                    # process model tensors
                    if 'df' in archi_type:
                        gpu_src_code     = self.inter(self.encoder(gpu_warped_src))
                        gpu_dst_code     = self.inter(self.encoder(gpu_warped_dst))
                        gpu_pred_src_src, gpu_pred_src_srcm = self.decoder_src(gpu_src_code)
                        gpu_pred_dst_dst, gpu_pred_dst_dstm = self.decoder_dst(gpu_dst_code)
                        gpu_pred_src_dst, gpu_pred_src_dstm = self.decoder_src(gpu_dst_code)

                    elif 'liae' in archi_type:
                        gpu_src_code = self.encoder (gpu_warped_src)
                        gpu_src_inter_AB_code = self.inter_AB (gpu_src_code)
                        gpu_src_code = tf.concat([gpu_src_inter_AB_code,gpu_src_inter_AB_code], nn.conv2d_ch_axis  )
                        gpu_dst_code = self.encoder (gpu_warped_dst)
                        gpu_dst_inter_B_code = self.inter_B (gpu_dst_code)
                        gpu_dst_inter_AB_code = self.inter_AB (gpu_dst_code)
                        gpu_dst_code = tf.concat([gpu_dst_inter_B_code,gpu_dst_inter_AB_code], nn.conv2d_ch_axis )
                        gpu_src_dst_code = tf.concat([gpu_dst_inter_AB_code,gpu_dst_inter_AB_code], nn.conv2d_ch_axis )

                        gpu_pred_src_src, gpu_pred_src_srcm = self.decoder(gpu_src_code)
                        gpu_pred_dst_dst, gpu_pred_dst_dstm = self.decoder(gpu_dst_code)
                        gpu_pred_src_dst, gpu_pred_src_dstm = self.decoder(gpu_src_dst_code)

                    gpu_pred_src_src_list.append(gpu_pred_src_src)
                    gpu_pred_dst_dst_list.append(gpu_pred_dst_dst)
                    gpu_pred_src_dst_list.append(gpu_pred_src_dst)

                    gpu_pred_src_srcm_list.append(gpu_pred_src_srcm)
                    gpu_pred_dst_dstm_list.append(gpu_pred_dst_dstm)
                    gpu_pred_src_dstm_list.append(gpu_pred_src_dstm)

                    gpu_target_srcm_blur = nn.gaussian_blur(gpu_target_srcm,  max(1, resolution // 32) )
                    gpu_target_srcm_blur = tf.clip_by_value(gpu_target_srcm_blur, 0, 0.5) * 2

                    gpu_target_dstm_blur = nn.gaussian_blur(gpu_target_dstm,  max(1, resolution // 32) )
                    gpu_target_dstm_style_blur = gpu_target_dstm_blur #default style mask is 0.5 on boundary
                    gpu_target_dstm_blur = tf.clip_by_value(gpu_target_dstm_blur, 0, 0.5) * 2

                    gpu_target_dst_masked           = gpu_target_dst*gpu_target_dstm_blur                    
                    gpu_target_dst_style_masked      = gpu_target_dst*gpu_target_dstm_style_blur
                    gpu_target_dst_style_anti_masked = gpu_target_dst*(1.0 - gpu_target_dstm_style_blur)

                    gpu_target_src_anti_masked = gpu_target_src*(1.0-gpu_target_srcm_blur)
                    gpu_target_src_masked_opt  = gpu_target_src*gpu_target_srcm_blur if masked_training else gpu_target_src
                    gpu_target_dst_masked_opt  = gpu_target_dst_masked if masked_training else gpu_target_dst

                    gpu_pred_src_src_masked_opt = gpu_pred_src_src*gpu_target_srcm_blur if masked_training else gpu_pred_src_src
                    gpu_pred_src_src_anti_masked = gpu_pred_src_src*(1.0-gpu_target_srcm_blur)
                    gpu_pred_dst_dst_masked_opt = gpu_pred_dst_dst*gpu_target_dstm_blur if masked_training else gpu_pred_dst_dst

                    gpu_psd_target_dst_style_masked = gpu_pred_src_dst*gpu_target_dstm_style_blur
                    gpu_psd_target_dst_style_anti_masked = gpu_pred_src_dst*(1.0 - gpu_target_dstm_style_blur)

                    if resolution < 256:
                        gpu_src_loss =  tf.reduce_mean ( 10*nn.dssim(gpu_target_src_masked_opt, gpu_pred_src_src_masked_opt, max_val=1.0, filter_size=int(resolution/11.6)), axis=[1])
                    else:
                        gpu_src_loss =  tf.reduce_mean ( 5*nn.dssim(gpu_target_src_masked_opt, gpu_pred_src_src_masked_opt, max_val=1.0, filter_size=int(resolution/11.6)), axis=[1])
                        gpu_src_loss += tf.reduce_mean ( 5*nn.dssim(gpu_target_src_masked_opt, gpu_pred_src_src_masked_opt, max_val=1.0, filter_size=int(resolution/23.2)), axis=[1])
                    gpu_src_loss += tf.reduce_mean ( 10*tf.square ( gpu_target_src_masked_opt - gpu_pred_src_src_masked_opt ), axis=[1,2,3])

                    if eyes_mouth_prio:
                        gpu_src_loss += tf.reduce_mean ( 300*tf.abs ( gpu_target_src*gpu_target_srcm_em - gpu_pred_src_src*gpu_target_srcm_em ), axis=[1,2,3])

                    gpu_src_loss += tf.reduce_mean ( 10*tf.square( gpu_target_srcm - gpu_pred_src_srcm ),axis=[1,2,3] )

                    face_style_power = self.options['face_style_power'] / 100.0
                    if face_style_power != 0 and not self.pretrain:
                        gpu_src_loss += nn.style_loss(gpu_psd_target_dst_style_masked, gpu_target_dst_style_masked, gaussian_blur_radius=resolution//16, loss_weight=10000*face_style_power)

                    bg_style_power = self.options['bg_style_power'] / 100.0
                    if bg_style_power != 0 and not self.pretrain:
                        gpu_src_loss += tf.reduce_mean( (10*bg_style_power)*nn.dssim( gpu_psd_target_dst_style_anti_masked,  gpu_target_dst_style_anti_masked, max_val=1.0, filter_size=int(resolution/11.6)), axis=[1])
                        gpu_src_loss += tf.reduce_mean( (10*bg_style_power)*tf.square(gpu_psd_target_dst_style_anti_masked - gpu_target_dst_style_anti_masked), axis=[1,2,3] )

                    if resolution < 256:
                        gpu_dst_loss = tf.reduce_mean ( 10*nn.dssim(gpu_target_dst_masked_opt, gpu_pred_dst_dst_masked_opt, max_val=1.0, filter_size=int(resolution/11.6) ), axis=[1])
                    else:
                        gpu_dst_loss = tf.reduce_mean ( 5*nn.dssim(gpu_target_dst_masked_opt, gpu_pred_dst_dst_masked_opt, max_val=1.0, filter_size=int(resolution/11.6) ), axis=[1])
                        gpu_dst_loss += tf.reduce_mean ( 5*nn.dssim(gpu_target_dst_masked_opt, gpu_pred_dst_dst_masked_opt, max_val=1.0, filter_size=int(resolution/23.2) ), axis=[1])
                    gpu_dst_loss += tf.reduce_mean ( 10*tf.square(  gpu_target_dst_masked_opt- gpu_pred_dst_dst_masked_opt ), axis=[1,2,3])

                    if eyes_mouth_prio:
                        gpu_dst_loss += tf.reduce_mean ( 300*tf.abs ( gpu_target_dst*gpu_target_dstm_em - gpu_pred_dst_dst*gpu_target_dstm_em ), axis=[1,2,3])

                    gpu_dst_loss += tf.reduce_mean ( 10*tf.square( gpu_target_dstm - gpu_pred_dst_dstm ),axis=[1,2,3] )

                    gpu_src_losses += [gpu_src_loss]
                    gpu_dst_losses += [gpu_dst_loss]

                    gpu_G_loss = gpu_src_loss + gpu_dst_loss

                    def DLoss(labels,logits):
                        return tf.reduce_mean( tf.nn.sigmoid_cross_entropy_with_logits(labels=labels, logits=logits), axis=[1,2,3])

                    if self.options['true_face_power'] != 0:
                        gpu_src_code_d = self.code_discriminator( gpu_src_code )
                        gpu_src_code_d_ones  = tf.ones_like (gpu_src_code_d)
                        gpu_src_code_d_zeros = tf.zeros_like(gpu_src_code_d)
                        gpu_dst_code_d = self.code_discriminator( gpu_dst_code )
                        gpu_dst_code_d_ones = tf.ones_like(gpu_dst_code_d)

                        gpu_G_loss += self.options['true_face_power']*DLoss(gpu_src_code_d_ones, gpu_src_code_d)

                        gpu_D_code_loss = (DLoss(gpu_src_code_d_ones , gpu_dst_code_d) + \
                                           DLoss(gpu_src_code_d_zeros, gpu_src_code_d) ) * 0.5

                        gpu_D_code_loss_gvs += [ nn.gradients (gpu_D_code_loss, self.code_discriminator.get_weights() ) ]

                    if gan_power != 0:
                        gpu_pred_src_src_d, \
                        gpu_pred_src_src_d2           = self.D_src(gpu_pred_src_src_masked_opt)

                        gpu_pred_src_src_d_ones  = tf.ones_like (gpu_pred_src_src_d)
                        gpu_pred_src_src_d_zeros = tf.zeros_like(gpu_pred_src_src_d)

                        gpu_pred_src_src_d2_ones  = tf.ones_like (gpu_pred_src_src_d2)
                        gpu_pred_src_src_d2_zeros = tf.zeros_like(gpu_pred_src_src_d2)

                        gpu_target_src_d, \
                        gpu_target_src_d2            = self.D_src(gpu_target_src_masked_opt)

                        gpu_target_src_d_ones    = tf.ones_like(gpu_target_src_d)
                        gpu_target_src_d2_ones    = tf.ones_like(gpu_target_src_d2)

                        gpu_D_src_dst_loss = (DLoss(gpu_target_src_d_ones      , gpu_target_src_d) + \
                                              DLoss(gpu_pred_src_src_d_zeros   , gpu_pred_src_src_d) ) * 0.5 + \
                                             (DLoss(gpu_target_src_d2_ones      , gpu_target_src_d2) + \
                                              DLoss(gpu_pred_src_src_d2_zeros   , gpu_pred_src_src_d2) ) * 0.5

                        gpu_D_src_dst_loss_gvs += [ nn.gradients (gpu_D_src_dst_loss, self.D_src.get_weights() ) ]#+self.D_src_x2.get_weights()

                        gpu_G_loss += gan_power*(DLoss(gpu_pred_src_src_d_ones, gpu_pred_src_src_d)  + \
                                                 DLoss(gpu_pred_src_src_d2_ones, gpu_pred_src_src_d2))



                        if masked_training:
                            # Minimal src-src-bg rec with total_variation_mse to suppress random bright dots from gan
                            gpu_G_loss += 0.000001*nn.total_variation_mse(gpu_pred_src_src)
                            gpu_G_loss += 0.02*tf.reduce_mean(tf.square(gpu_pred_src_src_anti_masked-gpu_target_src_anti_masked),axis=[1,2,3] )

                    gpu_G_loss_gvs += [ nn.gradients ( gpu_G_loss, self.src_dst_trainable_weights ) ]


            # Average losses and gradients, and create optimizer update ops
            with tf.device(f'/CPU:0'):
                pred_src_src  = nn.concat(gpu_pred_src_src_list, 0)
                pred_dst_dst  = nn.concat(gpu_pred_dst_dst_list, 0)
                pred_src_dst  = nn.concat(gpu_pred_src_dst_list, 0)
                pred_src_srcm = nn.concat(gpu_pred_src_srcm_list, 0)
                pred_dst_dstm = nn.concat(gpu_pred_dst_dstm_list, 0)
                pred_src_dstm = nn.concat(gpu_pred_src_dstm_list, 0)

            with tf.device (models_opt_device):
                src_loss = tf.concat(gpu_src_losses, 0)
                dst_loss = tf.concat(gpu_dst_losses, 0)
                src_dst_loss_gv_op = self.src_dst_opt.get_update_op (nn.average_gv_list (gpu_G_loss_gvs))

                if self.options['true_face_power'] != 0:
                    D_loss_gv_op = self.D_code_opt.get_update_op (nn.average_gv_list(gpu_D_code_loss_gvs))

                if gan_power != 0:
                    src_D_src_dst_loss_gv_op = self.D_src_dst_opt.get_update_op (nn.average_gv_list(gpu_D_src_dst_loss_gvs) )


            # Initializing training and view functions
            def src_dst_train(warped_src, target_src, target_srcm, target_srcm_em,  \
                              warped_dst, target_dst, target_dstm, target_dstm_em, ):
                s, d, _ = nn.tf_sess.run ( [ src_loss, dst_loss, src_dst_loss_gv_op],
                                            feed_dict={self.warped_src :warped_src,
                                                       self.target_src :target_src,
                                                       self.target_srcm:target_srcm,
                                                       self.target_srcm_em:target_srcm_em,
                                                       self.warped_dst :warped_dst,
                                                       self.target_dst :target_dst,
                                                       self.target_dstm:target_dstm,
                                                       self.target_dstm_em:target_dstm_em,
                                                       })
                return s, d
            self.src_dst_train = src_dst_train

            if self.options['true_face_power'] != 0:
                def D_train(warped_src, warped_dst):
                    nn.tf_sess.run ([D_loss_gv_op], feed_dict={self.warped_src: warped_src, self.warped_dst: warped_dst})
                self.D_train = D_train

            if gan_power != 0:
                def D_src_dst_train(warped_src, target_src, target_srcm, target_srcm_em,  \
                                    warped_dst, target_dst, target_dstm, target_dstm_em, ):
                    nn.tf_sess.run ([src_D_src_dst_loss_gv_op], feed_dict={self.warped_src :warped_src,
                                                                           self.target_src :target_src,
                                                                           self.target_srcm:target_srcm,
                                                                           self.target_srcm_em:target_srcm_em,
                                                                           self.warped_dst :warped_dst,
                                                                           self.target_dst :target_dst,
                                                                           self.target_dstm:target_dstm,
                                                                           self.target_dstm_em:target_dstm_em})
                self.D_src_dst_train = D_src_dst_train


            def AE_view(warped_src, warped_dst):
                return nn.tf_sess.run ( [pred_src_src, pred_dst_dst, pred_dst_dstm, pred_src_dst, pred_src_dstm],
                                            feed_dict={self.warped_src:warped_src,
                                                    self.warped_dst:warped_dst})
            self.AE_view = AE_view
        else:
            # Initializing merge function
            with tf.device( f'/GPU:0' if len(devices) != 0 else f'/CPU:0'):
                if 'df' in archi_type:
                    gpu_dst_code     = self.inter(self.encoder(self.warped_dst))
                    gpu_pred_src_dst, gpu_pred_src_dstm = self.decoder_src(gpu_dst_code)
                    _, gpu_pred_dst_dstm = self.decoder_dst(gpu_dst_code)

                elif 'liae' in archi_type:
                    gpu_dst_code = self.encoder (self.warped_dst)
                    gpu_dst_inter_B_code = self.inter_B (gpu_dst_code)
                    gpu_dst_inter_AB_code = self.inter_AB (gpu_dst_code)
                    gpu_dst_code = tf.concat([gpu_dst_inter_B_code,gpu_dst_inter_AB_code], nn.conv2d_ch_axis)
                    gpu_src_dst_code = tf.concat([gpu_dst_inter_AB_code,gpu_dst_inter_AB_code], nn.conv2d_ch_axis)

                    gpu_pred_src_dst, gpu_pred_src_dstm = self.decoder(gpu_src_dst_code)
                    _, gpu_pred_dst_dstm = self.decoder(gpu_dst_code)


            def AE_merge( warped_dst):
                return nn.tf_sess.run ( [gpu_pred_src_dst, gpu_pred_dst_dstm, gpu_pred_src_dstm], feed_dict={self.warped_dst:warped_dst})

            self.AE_merge = AE_merge

        # Loading/initializing all models/optimizers weights
        for model, filename in io.progress_bar_generator(self.model_filename_list, "初始化模型"):
            if self.pretrain_just_disabled:
                do_init = False
                if 'df' in archi_type:
                    if model == self.inter:
                        do_init = True
                elif 'liae' in archi_type:
                    if model == self.inter_AB or model == self.inter_B:
                        do_init = True
            else:
                do_init = self.is_first_run()
                if self.is_training and gan_power != 0 and model == self.D_src:
                    if self.gan_model_changed:
                        do_init = True

            if not do_init:
                do_init = not model.load_weights( self.get_strpath_storage_for_file(filename) )

            if do_init:
                model.init_weights()

        # initializing sample generators
        if self.is_training:
            training_data_src_path = self.training_data_src_path if not self.pretrain else self.get_pretraining_data_path()
            training_data_dst_path = self.training_data_dst_path if not self.pretrain else self.get_pretraining_data_path()

            random_ct_samples_path=training_data_dst_path if ct_mode is not None and not self.pretrain else None

            cpu_count = min(multiprocessing.cpu_count(), 8)
            src_generators_count = cpu_count // 2
            dst_generators_count = cpu_count // 2
            if ct_mode is not None:
                src_generators_count = int(src_generators_count * 1.5)

            self.set_training_data_generators ([
                    SampleGeneratorFace(training_data_src_path, random_ct_samples_path=random_ct_samples_path, debug=self.is_debug(), batch_size=self.get_batch_size(),
                        sample_process_options=SampleProcessor.Options(random_flip=self.random_flip),
                        output_sample_types = [ {'sample_type': SampleProcessor.SampleType.FACE_IMAGE,'warp':random_warp, 'transform':True, 'channel_type' : SampleProcessor.ChannelType.BGR, 'ct_mode': ct_mode,                                           'face_type':self.face_type, 'data_format':nn.data_format, 'resolution': resolution},
                                                {'sample_type': SampleProcessor.SampleType.FACE_IMAGE,'warp':False                      , 'transform':True, 'channel_type' : SampleProcessor.ChannelType.BGR, 'ct_mode': ct_mode,                                           'face_type':self.face_type, 'data_format':nn.data_format, 'resolution': resolution},
                                                {'sample_type': SampleProcessor.SampleType.FACE_MASK, 'warp':False                      , 'transform':True, 'channel_type' : SampleProcessor.ChannelType.G,   'face_mask_type' : SampleProcessor.FaceMaskType.FULL_FACE, 'face_type':self.face_type, 'data_format':nn.data_format, 'resolution': resolution},
                                                {'sample_type': SampleProcessor.SampleType.FACE_MASK, 'warp':False                      , 'transform':True, 'channel_type' : SampleProcessor.ChannelType.G,   'face_mask_type' : SampleProcessor.FaceMaskType.EYES_MOUTH, 'face_type':self.face_type, 'data_format':nn.data_format, 'resolution': resolution},
                                              ],
                        uniform_yaw_distribution=self.options['uniform_yaw'] or self.pretrain,
                        generators_count=src_generators_count ),

                    SampleGeneratorFace(training_data_dst_path, debug=self.is_debug(), batch_size=self.get_batch_size(),
                        sample_process_options=SampleProcessor.Options(random_flip=self.random_flip),
                        output_sample_types = [ {'sample_type': SampleProcessor.SampleType.FACE_IMAGE,'warp':random_warp, 'transform':True, 'channel_type' : SampleProcessor.ChannelType.BGR,                                                                'face_type':self.face_type, 'data_format':nn.data_format, 'resolution': resolution},
                                                {'sample_type': SampleProcessor.SampleType.FACE_IMAGE,'warp':False                      , 'transform':True, 'channel_type' : SampleProcessor.ChannelType.BGR,                                                                'face_type':self.face_type, 'data_format':nn.data_format, 'resolution': resolution},
                                                {'sample_type': SampleProcessor.SampleType.FACE_MASK, 'warp':False                      , 'transform':True, 'channel_type' : SampleProcessor.ChannelType.G,   'face_mask_type' : SampleProcessor.FaceMaskType.FULL_FACE, 'face_type':self.face_type, 'data_format':nn.data_format, 'resolution': resolution},
                                                {'sample_type': SampleProcessor.SampleType.FACE_MASK, 'warp':False                      , 'transform':True, 'channel_type' : SampleProcessor.ChannelType.G,   'face_mask_type' : SampleProcessor.FaceMaskType.EYES_MOUTH, 'face_type':self.face_type, 'data_format':nn.data_format, 'resolution': resolution},
                                              ],
                        uniform_yaw_distribution=self.options['uniform_yaw'] or self.pretrain,
                        generators_count=dst_generators_count )
                             ])

            self.last_src_samples_loss = []
            self.last_dst_samples_loss = []

            if self.pretrain_just_disabled:
                self.update_sample_for_preview(force_new=True)

    #override
    def get_model_filename_list(self):
        return self.model_filename_list

    #override
    def onSave(self):
        for model, filename in io.progress_bar_generator(self.get_model_filename_list(), "保存中", leave=False):
            model.save_weights ( self.get_strpath_storage_for_file(filename) )

    #override
    def should_save_preview_history(self):
        return (not io.is_colab() and self.iter % ( 10*(max(1,self.resolution // 64)) ) == 0) or \
               (io.is_colab() and self.iter % 100 == 0)

    #override
    def onTrainOneIter(self):
        if self.get_iter() == 0 and not self.pretrain and not self.pretrain_just_disabled:
            io.log_info('您正在从头开始训练模型！为了加快训练速度，提高质量，建议购买训练好的模型使用。\n')

        bs = self.get_batch_size()

        ( (warped_src, target_src, target_srcm, target_srcm_em), \
          (warped_dst, target_dst, target_dstm, target_dstm_em) ) = self.generate_next_samples()

        src_loss, dst_loss = self.src_dst_train (warped_src, target_src, target_srcm, target_srcm_em, warped_dst, target_dst, target_dstm, target_dstm_em)

        for i in range(bs):
            self.last_src_samples_loss.append (  (target_src[i], target_srcm[i], target_srcm_em[i], src_loss[i] )  )
            self.last_dst_samples_loss.append (  (target_dst[i], target_dstm[i], target_dstm_em[i], dst_loss[i] )  )

        if len(self.last_src_samples_loss) >= bs*16:
            src_samples_loss = sorted(self.last_src_samples_loss, key=operator.itemgetter(3), reverse=True)
            dst_samples_loss = sorted(self.last_dst_samples_loss, key=operator.itemgetter(3), reverse=True)

            target_src        = np.stack( [ x[0] for x in src_samples_loss[:bs] ] )
            target_srcm       = np.stack( [ x[1] for x in src_samples_loss[:bs] ] )
            target_srcm_em = np.stack( [ x[2] for x in src_samples_loss[:bs] ] )

            target_dst        = np.stack( [ x[0] for x in dst_samples_loss[:bs] ] )
            target_dstm       = np.stack( [ x[1] for x in dst_samples_loss[:bs] ] )
            target_dstm_em = np.stack( [ x[2] for x in dst_samples_loss[:bs] ] )

            src_loss, dst_loss = self.src_dst_train (target_src, target_src, target_srcm, target_srcm_em, target_dst, target_dst, target_dstm, target_dstm_em)
            self.last_src_samples_loss = []
            self.last_dst_samples_loss = []

        if self.options['true_face_power'] != 0 and not self.pretrain:
            self.D_train (warped_src, warped_dst)

        if self.gan_power != 0:
            self.D_src_dst_train (warped_src, target_src, target_srcm, target_srcm_em, warped_dst, target_dst, target_dstm, target_dstm_em)

        return ( ('src_loss', np.mean(src_loss) ), ('dst_loss', np.mean(dst_loss) ), )

    #override
    def onGetPreview(self, samples):
        ( (warped_src, target_src, target_srcm, target_srcm_em),
          (warped_dst, target_dst, target_dstm, target_dstm_em) ) = samples

        S, D, SS, DD, DDM, SD, SDM = [ np.clip( nn.to_data_format(x,"NHWC", self.model_data_format), 0.0, 1.0) for x in ([target_src,target_dst] + self.AE_view (target_src, target_dst) ) ]
        DDM, SDM, = [ np.repeat (x, (3,), -1) for x in [DDM, SDM] ]

        target_srcm, target_dstm = [ nn.to_data_format(x,"NHWC", self.model_data_format) for x in ([target_srcm, target_dstm] )]

        n_samples = min(4, self.get_batch_size(), 1024 // self.resolution )

        if self.resolution <= 1024:
            result = []

            st = []
            for i in range(n_samples):
                ar = S[i], SS[i], D[i], DD[i], SD[i]
                st.append ( np.concatenate ( ar, axis=1) )
            result += [ ('HackFake', np.concatenate (st, axis=0 )), ]


            st_m = []
            for i in range(n_samples):
                SD_mask = DDM[i]*SDM[i] if self.face_type < FaceType.HEAD else SDM[i]

                ar = S[i]*target_srcm[i], SS[i], D[i]*target_dstm[i], DD[i]*DDM[i], SD[i]*SD_mask
                st_m.append ( np.concatenate ( ar, axis=1) )

            result += [ ('HackFake masked', np.concatenate (st_m, axis=0 )), ]
        else:
            result = []

            st = []
            for i in range(n_samples):
                ar = S[i], SS[i]
                st.append ( np.concatenate ( ar, axis=1) )
            result += [ ('HackFake src-src', np.concatenate (st, axis=0 )), ]

            st = []
            for i in range(n_samples):
                ar = D[i], DD[i]
                st.append ( np.concatenate ( ar, axis=1) )
            result += [ ('HackFake dst-dst', np.concatenate (st, axis=0 )), ]

            st = []
            for i in range(n_samples):
                ar = D[i], SD[i]
                st.append ( np.concatenate ( ar, axis=1) )
            result += [ ('HackFake pred', np.concatenate (st, axis=0 )), ]


            st_m = []
            for i in range(n_samples):
                ar = S[i]*target_srcm[i], SS[i]
                st_m.append ( np.concatenate ( ar, axis=1) )
            result += [ ('HackFake masked src-src', np.concatenate (st_m, axis=0 )), ]

            st_m = []
            for i in range(n_samples):
                ar = D[i]*target_dstm[i], DD[i]*DDM[i]
                st_m.append ( np.concatenate ( ar, axis=1) )
            result += [ ('HackFake masked dst-dst', np.concatenate (st_m, axis=0 )), ]

            st_m = []
            for i in range(n_samples):
                SD_mask = DDM[i]*SDM[i] if self.face_type < FaceType.HEAD else SDM[i]
                ar = D[i]*target_dstm[i], SD[i]*SD_mask
                st_m.append ( np.concatenate ( ar, axis=1) )
            result += [ ('HackFake masked pred', np.concatenate (st_m, axis=0 )), ]

        return result

    def predictor_func (self, face=None):
        face = nn.to_data_format(face[None,...], self.model_data_format, "NHWC")

        bgr, mask_dst_dstm, mask_src_dstm = [ nn.to_data_format(x,"NHWC", self.model_data_format).astype(np.float32) for x in self.AE_merge (face) ]

        return bgr[0], mask_src_dstm[0][...,0], mask_dst_dstm[0][...,0]

    #override
    def get_MergerConfig(self):
        import merger
        return self.predictor_func, (self.options['resolution'], self.options['resolution'], 3), merger.MergerConfigMasked(face_type=self.face_type, default_mode = 'overlay')

Model = HackFakeModel
